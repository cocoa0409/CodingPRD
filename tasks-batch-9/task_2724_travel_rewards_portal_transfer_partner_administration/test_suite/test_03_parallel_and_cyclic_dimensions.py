"""
Non-linear state machines: the two independent dimensions of a redemption order,
and the hold/release cycle of a transfer request escalating an account's posture.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_account_aggregates
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    ANALYST_USER_ID,
    APPROVER_HEADERS,
    APPROVER_USER_ID,
)
from test_helpers.types import (
    BENEFIT_LOUNGE_ACCESS,
    BENEFIT_TRAVEL_INSURANCE,
    CATEGORY_DINING,
    CATEGORY_GROCERY,
    ENTITLEMENT_ACTIVE,
    ENTITLEMENT_SUSPENDED,
    FULFILLMENT_CANCELLED,
    FULFILLMENT_TICKETED,
    HOLD_ATO_SUSPECTED,
    HOLD_MANUAL_REVIEW,
    OFFER_OPEN,
    OFFER_SOLD_OUT,
    POSTURE_CLEAR,
    POSTURE_WATCH,
    PRODUCT_PREMIER,
    SETTLEMENT_SETTLED,
    SETTLEMENT_UNSETTLED,
    SUSPENSION_POSTURE_WATCH,
    TRANSFER_HELD,
    TRANSFER_SUBMITTED,
)

DINING_MCC = "5812"
GROCERY_MCC = "5411"


def _two_bookings_on_one_offer(api):
    """A 2-seat offer with two quotes: one kept and walked to settlement, one dropped."""
    fx.ensure_mapping(
        api,
        ADMIN_HEADERS,
        mcc_code=DINING_MCC,
        display_name="Restaurants",
        base_category=CATEGORY_DINING,
        base_multiplier=3.0,
    )
    account = fx.new_account(api, ADMIN_HEADERS, card_product_code=PRODUCT_PREMIER)
    cardholder = fx.account_holder(account)
    fx.post_purchase(
        api, account["id"], 1600000, headers=ADMIN_HEADERS, mcc_code=DINING_MCC
    )
    agency, offer, supplier = fx.agency_with_offer(
        api,
        ADMIN_HEADERS,
        agency={"contracted_markup_bps": 2000, "parity_tolerance_bps": 1000},
        net_rate_cents=40000,
        agency_public_price_cents=50000,
        agency_public_seats=3,
        portal_seats=2,
        tax_cents=4000,
    )
    kept = fx.book(api, offer, account["id"], cardholder)
    fresh = fx.read_offer(api, offer["id"])
    dropped = fx.book(api, fresh, account["id"], cardholder)
    assert fx.read_offer(api, offer["id"])["status"] == OFFER_SOLD_OUT
    return account, cardholder, agency, offer, supplier, kept, dropped


def test_settlement_reaches_settled_while_fulfillment_stays_at_ticketed(api):
    """
    "The two advance independently. Settling an invoice never moves
    `fulfillment_status`, and cancelling before ticketing never moves
    `settlement_status` off `UNSETTLED`."

    Design: Difficulty/non_linear_state_machine/parallel_dimensions_settlement_advances_without_moving_fulfillment
    """
    _, cardholder, _, _, supplier, kept, _ = _two_bookings_on_one_offer(api)

    fx.confirm(api, kept["id"], cardholder)
    fx.ticket(api, kept["id"], supplier)
    settled = fx.settle(api, kept["id"], 40000, settlement_adjustment_cents=0)

    assert settled["fulfillment_status"] == FULFILLMENT_TICKETED
    assert settled["settlement_status"] == SETTLEMENT_SETTLED
    assert settled["issuer_cost_final_cents"] == 36000
    assert settled["ticket_number"] == "TKT-0001"


def test_cancelling_a_quote_moves_fulfillment_only_and_reopens_the_sold_out_offer(api):
    """
    "Cancelling from `QUOTED` lowers `points_pending_redemption` by `points_debited`
    and appends no ledger entry at all, because nothing was ever debited. ... Both
    branches ... recompute the offer's `seats_committed` so that a `SOLD_OUT` offer
    returns to `OPEN`, leave `settlement_status` at `UNSETTLED` ..."

    Design: Difficulty/non_linear_state_machine/parallel_dimensions_settlement_advances_without_moving_fulfillment
    """
    _, cardholder, _, offer, supplier, kept, dropped = _two_bookings_on_one_offer(api)
    fx.confirm(api, kept["id"], cardholder)
    fx.ticket(api, kept["id"], supplier)
    fx.settle(api, kept["id"], 40000, settlement_adjustment_cents=0)

    cancelled = validate_success(
        api.cancel_order(
            dropped["id"], {"closed_reason": "Traveller withdrew"}, cardholder
        )
    )
    assert cancelled["fulfillment_status"] == FULFILLMENT_CANCELLED
    assert cancelled["settlement_status"] == SETTLEMENT_UNSETTLED

    reopened = fx.read_offer(api, offer["id"])
    assert reopened["status"] == OFFER_OPEN
    assert reopened["seats_committed"] == 1


def test_the_cash_dimension_owes_only_the_settled_seat_after_the_other_is_cancelled(api):
    """
    "`payable_cents` is the outstanding cash the issuer owes this agency; it is
    derived and moves only through the ticket, settle, and refund transitions ..."

    Design: Difficulty/non_linear_state_machine/parallel_dimensions_settlement_advances_without_moving_fulfillment
    """
    account, cardholder, agency, _, supplier, kept, dropped = _two_bookings_on_one_offer(api)
    fx.confirm(api, kept["id"], cardholder)
    fx.ticket(api, kept["id"], supplier)
    fx.settle(api, kept["id"], 40000, settlement_adjustment_cents=0)
    validate_success(
        api.cancel_order(
            dropped["id"], {"closed_reason": "Traveller withdrew"}, cardholder
        )
    )

    assert (
        validate_success(api.get_agency_partner(agency["id"], ADMIN_HEADERS))[
            "payable_cents"
        ]
        == 36000
    )
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=36800,
        points_pending_redemption=0,
    )


def _held_then_released_transfer(api):
    """A 4,000-point transfer held by an analyst and released by an approver."""
    fx.ensure_mapping(
        api,
        ADMIN_HEADERS,
        mcc_code=GROCERY_MCC,
        display_name="Supermarkets",
        base_category=CATEGORY_GROCERY,
        base_multiplier=1.0,
    )
    account, cardholder = fx.funded_account(api, 0)
    fx.fund_account(api, account["id"], 5000, mcc_code=GROCERY_MCC)
    lounge = fx.grant_entitlement(
        api,
        account["id"],
        ADMIN_HEADERS,
        benefit_type=BENEFIT_LOUNGE_ACCESS,
        annual_allowance=4,
        requires_portal_booking=False,
    )
    insurance = fx.grant_entitlement(
        api,
        account["id"],
        ADMIN_HEADERS,
        benefit_type=BENEFIT_TRAVEL_INSURANCE,
        annual_allowance=2,
        requires_portal_booking=False,
    )
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
    transfer = fx.submit_transfer(
        api, account["id"], agreement["id"], 4000, cardholder
    )
    fx.hold_transfer(api, transfer["id"], ANALYST_HEADERS, HOLD_MANUAL_REVIEW)
    released = validate_success(
        api.release_transfer(transfer["id"], {}, APPROVER_HEADERS)
    )
    return account, transfer, released, lounge, insurance


def test_release_returns_the_request_to_screening_but_leaves_the_hold_facts_standing(api):
    """
    "Release stores `released_by_user_id`, clears `scheduled_post_at`, and increments
    the request's `version` by 1 — and deliberately leaves both `hold_reason` and the
    account's `transfer_hold_count` standing as historical facts."

    Design: Difficulty/non_linear_state_machine/cyclic_transfer_hold_release_then_held_again_escalates_posture
    """
    account, _, released, lounge, insurance = _held_then_released_transfer(api)

    assert released["status"] == TRANSFER_SUBMITTED
    assert released["hold_reason"] == HOLD_MANUAL_REVIEW
    assert released["released_by_user_id"] == APPROVER_USER_ID
    assert released["scheduled_post_at"] is None

    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=1000,
        points_pending_redemption=4000,
        transfer_hold_count=1,
        fraud_posture=POSTURE_CLEAR,
    )
    assert fx.read_entitlement(api, lounge["id"])["status"] == ENTITLEMENT_ACTIVE
    assert fx.read_entitlement(api, insurance["id"])["status"] == ENTITLEMENT_ACTIVE


def test_a_second_hold_reaches_two_and_watches_the_account_suspending_lounge_access(api):
    """
    "Every hold increments the account's `transfer_hold_count` by 1 and then re-runs
    the posture calculation, which may move the account `CLEAR` → `WATCH` and suspend
    its lounge-access entitlements."

    Design: Difficulty/non_linear_state_machine/cyclic_transfer_hold_release_then_held_again_escalates_posture
    """
    account, transfer, _, lounge, insurance = _held_then_released_transfer(api)

    held_again = fx.hold_transfer(
        api, transfer["id"], ANALYST_HEADERS, HOLD_ATO_SUSPECTED
    )
    assert held_again["status"] == TRANSFER_HELD
    assert held_again["hold_reason"] == HOLD_ATO_SUSPECTED
    assert held_again["held_by_user_id"] == ANALYST_USER_ID
    assert held_again["released_by_user_id"] == APPROVER_USER_ID
    assert held_again["scheduled_post_at"] is None

    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=1000,
        points_pending_redemption=4000,
        transfer_hold_count=2,
        fraud_posture=POSTURE_WATCH,
    )
    suspended = fx.read_entitlement(api, lounge["id"])
    assert suspended["status"] == ENTITLEMENT_SUSPENDED
    assert suspended["suspension_reason"] == SUSPENSION_POSTURE_WATCH
    assert fx.read_entitlement(api, insurance["id"])["status"] == ENTITLEMENT_ACTIVE
