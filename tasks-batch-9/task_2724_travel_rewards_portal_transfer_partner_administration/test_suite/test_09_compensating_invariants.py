"""
Two conserved quantities: the cardholder's points total across a transfer that is
submitted, held and rejected, and the agency's payable across ticket, settle, refund.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_account_aggregates,
    assert_conserved_quantity,
    assert_ledger_entry,
    assert_ledger_entry_types,
    read_ledger,
)
from test_helpers.test_users import ADMIN_HEADERS, ANALYST_HEADERS, APPROVER_HEADERS
from test_helpers.types import (
    CATEGORY_DINING,
    CATEGORY_GROCERY,
    ENTRY_EARN_BASE,
    ENTRY_TRANSFER_DEBIT,
    ENTRY_TRANSFER_REVERSAL,
    FULFILLMENT_REFUNDED,
    HOLD_ATO_SUSPECTED,
    OFFER_OPEN,
    PRODUCT_PREMIER,
    SETTLEMENT_CLAWED_BACK,
    TRANSFER_HELD,
    TRANSFER_REJECTED,
)

DINING_MCC = "5812"
GROCERY_MCC = "5411"


def _held_four_thousand_point_transfer(api):
    """A 4,000-point transfer out of a 10,000-point balance, currently `HELD`."""
    fx.ensure_mapping(
        api,
        ADMIN_HEADERS,
        mcc_code=GROCERY_MCC,
        display_name="Grocery Stores",
        base_category=CATEGORY_GROCERY,
        base_multiplier=1.0,
    )
    account, cardholder = fx.funded_account(
        api, 0, cardholder_name="Mira Delcourt", email="mira@example.com"
    )
    fx.fund_account(api, account["id"], 10000, mcc_code=GROCERY_MCC)
    agreement = fx.active_agreement(
        api,
        ADMIN_HEADERS,
        APPROVER_HEADERS,
        partner_name="Skyward Miles",
        partner_program_code="SKYW",
        transfer_latency_hours=48,
        reversal_window_hours=72,
        settlement_cost_cents_per_1k=900,
    )
    transfer = fx.submit_transfer(api, account["id"], agreement["id"], 4000, cardholder)
    return account, transfer


def test_submission_and_the_hold_both_leave_the_points_total_at_ten_thousand(api):
    """
    "reserving points moves them from one term to the other, and cancelling or
    rejecting moves them back, so the sum returns to exactly what it was before."

    Design: Difficulty/compensating_invariant/invariant_points_conserved_across_transfer_submit_and_rejection
    """
    account, transfer = _held_four_thousand_point_transfer(api)

    after_submit = fx.read_account(api, account["id"])
    assert_account_aggregates(
        after_submit, points_balance=6000, points_pending_redemption=4000
    )
    assert_conserved_quantity(after_submit, 10000)

    held = fx.hold_transfer(api, transfer["id"], ANALYST_HEADERS, HOLD_ATO_SUSPECTED)

    assert held["status"] == TRANSFER_HELD
    after_hold = fx.read_account(api, account["id"])
    assert_account_aggregates(
        after_hold, points_balance=6000, points_pending_redemption=4000
    )
    assert_conserved_quantity(after_hold, 10000)


def test_rejection_writes_the_compensating_entry_and_restores_the_balance(api):
    """
    "The `HELD` → `REJECTED` transition appends a `TRANSFER_REVERSAL` ledger entry of
    positive `points_out`, restoring `points_balance` to its pre-submission value, and
    lowers `points_pending_redemption` by `points_out`, so the conserved sum returns
    to exactly what it was before the transfer existed."

    Design: Difficulty/compensating_invariant/invariant_points_conserved_across_transfer_submit_and_rejection
    """
    account, transfer = _held_four_thousand_point_transfer(api)
    fx.hold_transfer(api, transfer["id"], ANALYST_HEADERS, HOLD_ATO_SUSPECTED)

    rejected = validate_success(
        api.reject_transfer(
            transfer["id"],
            f.resolution_payload("CARDHOLDER_DENIED_REQUEST"),
            ANALYST_HEADERS,
        )
    )

    assert rejected["status"] == TRANSFER_REJECTED
    assert rejected["resolution_reason"] == "CARDHOLDER_DENIED_REQUEST"
    after = fx.read_account(api, account["id"])
    assert_account_aggregates(
        after,
        points_balance=10000,
        points_pending_redemption=0,
        lifetime_points_earned=10000,
    )
    assert_conserved_quantity(after, 10000)

    entries = read_ledger(api, ADMIN_HEADERS, account["id"])
    assert_ledger_entry_types(
        entries, [ENTRY_EARN_BASE, ENTRY_TRANSFER_DEBIT, ENTRY_TRANSFER_REVERSAL]
    )
    assert_ledger_entry(
        entries[1],
        entry_type=ENTRY_TRANSFER_DEBIT,
        points_delta=-4000,
        balance_after=6000,
        source_entity_id=transfer["id"],
    )
    assert_ledger_entry(
        entries[2],
        entry_type=ENTRY_TRANSFER_REVERSAL,
        points_delta=4000,
        balance_after=10000,
        source_entity_id=transfer["id"],
    )


def _ticketable_booking(api):
    """A confirmed 35,200-point booking whose provisional issuer cost is 36,000."""
    fx.ensure_mapping(
        api,
        ADMIN_HEADERS,
        mcc_code=DINING_MCC,
        display_name="Restaurants",
        base_category=CATEGORY_DINING,
        base_multiplier=3.0,
    )
    account = fx.new_account(
        api,
        ADMIN_HEADERS,
        cardholder_name="Sasha Belanger",
        email="sasha@example.com",
        card_product_code=PRODUCT_PREMIER,
    )
    cardholder = fx.account_holder(account)
    fx.post_purchase(api, account["id"], 1600000, ADMIN_HEADERS, mcc_code=DINING_MCC)
    agency, offer, supplier = fx.agency_with_offer(
        api,
        ADMIN_HEADERS,
        agency={
            "name": "Northwind Travel",
            "contracted_markup_bps": 2000,
            "parity_tolerance_bps": 1000,
        },
        itinerary_code="SFO-AMS-05",
        net_rate_cents=40000,
        agency_public_price_cents=50000,
        agency_public_seats=3,
        portal_seats=2,
        tax_cents=4000,
    )
    order = fx.book(
        api, offer, account["id"], cardholder, traveler_name="Sasha Belanger"
    )
    assert order["points_debited"] == 35200
    fx.confirm(api, order["id"], cardholder)
    return account, agency, offer, order, supplier


def _payable(api, agency_id):
    return validate_success(api.get_agency_partner(agency_id, ADMIN_HEADERS))[
        "payable_cents"
    ]


def test_ticketing_credits_exactly_the_provisional_cost(api):
    """
    "The order's forward-looking cost to the issuer, `issuer_cost_provisional_cents`,
    is the offer's `net_rate_cents` less the order's `cash_copay_cents`, and
    `cost_per_1k_provisional_cents` is that provisional cost multiplied by 1,000,
    divided by `points_debited`, rounded half up to whole cents"

    Design: Difficulty/compensating_invariant/invariant_agency_payable_conserved_across_ticket_settle_and_refund
    """
    _, agency, _, order, supplier = _ticketable_booking(api)

    ticketed = fx.ticket(api, order["id"], supplier, "TKT-90021")

    assert ticketed["issuer_cost_provisional_cents"] == 36000
    assert ticketed["cost_per_1k_provisional_cents"] == 1023
    assert _payable(api, agency["id"]) == 36000


def test_settlement_trues_the_payable_up_to_the_final_cost(api):
    """
    "On success the agency's `payable_cents` is adjusted by the final cost less the
    provisional cost — a figure that is negative whenever the agency invoiced less
    than its booking-time net rate implied"

    Design: Difficulty/compensating_invariant/invariant_agency_payable_conserved_across_ticket_settle_and_refund
    """
    _, agency, _, order, supplier = _ticketable_booking(api)
    fx.ticket(api, order["id"], supplier, "TKT-90021")

    settled = fx.settle(api, order["id"], 41000, settlement_adjustment_cents=-500)

    assert settled["issuer_cost_final_cents"] == 36500
    assert settled["cost_per_1k_final_cents"] == 1037
    assert settled["issuer_cost_provisional_cents"] == 36000
    assert _payable(api, agency["id"]) == 36500


def test_the_refund_subtracts_the_settled_figure_and_returns_the_payable_to_zero(api):
    """
    "subtracts from the agency's `payable_cents` **exactly the amount previously
    added** — `issuer_cost_final_cents` when the order had already reached `SETTLED`,
    and `issuer_cost_provisional_cents` otherwise."

    Design: Difficulty/compensating_invariant/invariant_agency_payable_conserved_across_ticket_settle_and_refund
    """
    account, agency, offer, order, supplier = _ticketable_booking(api)
    fx.ticket(api, order["id"], supplier, "TKT-90021")
    fx.settle(api, order["id"], 41000, settlement_adjustment_cents=-500)

    refunded = validate_success(
        api.refund_order(
            order["id"], f.cancel_payload("AIRLINE_CANCELLED_ROUTE"), supplier
        )
    )

    assert refunded["fulfillment_status"] == FULFILLMENT_REFUNDED
    assert refunded["settlement_status"] == SETTLEMENT_CLAWED_BACK
    assert _payable(api, agency["id"]) == 0
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=72000,
        points_pending_redemption=0,
    )
    after_offer = fx.read_offer(api, offer["id"], supplier)
    assert after_offer["seats_committed"] == 0
    assert after_offer["status"] == OFFER_OPEN
