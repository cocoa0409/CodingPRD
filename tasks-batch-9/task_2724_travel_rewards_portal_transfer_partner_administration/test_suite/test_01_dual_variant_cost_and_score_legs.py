"""
Two-variant calculations: the provisional and final issuer-cost legs of a
redemption order, and the instant and review legs of an account-takeover score.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_account_aggregates,
    assert_ledger_entry,
    assert_ledger_entry_types,
    read_ledger,
)
from test_helpers.test_users import ADMIN_HEADERS, ANALYST_HEADERS, APPROVER_HEADERS
from test_helpers.types import (
    BENEFIT_LOUNGE_ACCESS,
    BENEFIT_TRAVEL_INSURANCE,
    CASE_ACCOUNT_TAKEOVER,
    CASE_OPEN,
    CASE_UNDER_REVIEW,
    CATEGORY_DINING,
    ENTITLEMENT_ACTIVE,
    ENTITLEMENT_SUSPENDED,
    ENTRY_EARN_BASE,
    ENTRY_TRANSFER_DEBIT,
    ENTRY_TRANSFER_REVERSAL,
    FULFILLMENT_TICKETED,
    PARITY_IN,
    POSTURE_LOCKED,
    POSTURE_WATCH,
    PRODUCT_PREMIER,
    RESOLUTION_POSTURE_LOCKED,
    SETTLEMENT_AGENCY_INVOICED,
    SETTLEMENT_SETTLED,
    SIGNAL_DEVICE_CHANGE,
    SIGNAL_EMAIL_CHANGE,
    SUSPENSION_POSTURE_LOCKED,
    SUSPENSION_POSTURE_WATCH,
    TRANSFER_REJECTED,
    TRANSFER_SUBMITTED,
)

DINING_MCC = "5812"


def _premier_dining_account(api, spend_cents):
    """A `PREMIER` account funded through one 3.0x dining purchase."""
    fx.ensure_mapping(
        api,
        ADMIN_HEADERS,
        mcc_code=DINING_MCC,
        display_name="Restaurants",
        base_category=CATEGORY_DINING,
        base_multiplier=3.0,
    )
    account = fx.new_account(
        api, ADMIN_HEADERS, card_product_code=PRODUCT_PREMIER
    )
    fx.post_purchase(
        api, account["id"], spend_cents, headers=ADMIN_HEADERS, mcc_code=DINING_MCC
    )
    return fx.read_account(api, account["id"]), fx.account_holder(account)


def _quoted_portal_booking(api):
    """A `PREMIER` cardholder holding 36,000 points with one quoted booking."""
    account, cardholder = _premier_dining_account(api, 800000)
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
    order = fx.book(api, offer, account["id"], cardholder)
    return account, cardholder, agency, offer, supplier, order


def test_earning_multipliers_price_the_quote_and_its_provisional_cost_leg(api):
    """
    "`issuer_cost_provisional_cents`, is the offer's `net_rate_cents` less the
    order's `cash_copay_cents`, and `cost_per_1k_provisional_cents` is that
    provisional cost multiplied by 1,000, divided by `points_debited`, rounded
    half up to whole cents ..."

    Design: Difficulty/dual_variant_calc/dual_variant_redemption_issuer_cost_provisional_vs_final
    """
    account, _, _, offer, _, order = _quoted_portal_booking(api)

    assert account["points_balance"] == 36000
    assert offer["portal_price_cents"] == 48000
    assert offer["cash_copay_cents"] == 4000
    assert offer["parity_status"] == PARITY_IN

    assert order["cents_per_point_applied"] == 1.25
    assert order["cash_copay_cents"] == 4000
    assert order["points_debited"] == 35200
    assert order["issuer_cost_provisional_cents"] == 36000
    assert order["cost_per_1k_provisional_cents"] == 1023
    assert order["issuer_cost_final_cents"] is None
    assert order["cost_per_1k_final_cents"] is None


def test_settlement_adds_the_final_cost_leg_beside_the_untouched_provisional_one(api):
    """
    "The two cost legs are stored side by side and never overwrite each other: the
    provisional leg reads only the offer snapshot captured at booking, and the final
    leg reads only the settlement inputs ..."

    Design: Difficulty/dual_variant_calc/dual_variant_redemption_issuer_cost_provisional_vs_final
    """
    _, cardholder, _, _, supplier, order = _quoted_portal_booking(api)
    fx.confirm(api, order["id"], cardholder)
    fx.ticket(api, order["id"], supplier)
    settled = fx.settle(
        api, order["id"], 41000, settlement_adjustment_cents=-500
    )

    assert settled["fulfillment_status"] == FULFILLMENT_TICKETED
    assert settled["settlement_status"] == SETTLEMENT_SETTLED
    assert settled["issuer_cost_provisional_cents"] == 36000
    assert settled["cost_per_1k_provisional_cents"] == 1023
    assert settled["issuer_cost_final_cents"] == 36500
    assert settled["cost_per_1k_final_cents"] == 1037


def test_agency_payable_moves_by_the_gap_between_the_two_cost_legs(api):
    """
    "the agency's `payable_cents` is adjusted by the final cost less the provisional
    cost — a figure that is negative whenever the agency invoiced less than its
    booking-time net rate implied ..."

    Design: Difficulty/dual_variant_calc/dual_variant_redemption_issuer_cost_provisional_vs_final
    """
    account, cardholder, agency, _, supplier, order = _quoted_portal_booking(api)
    fx.confirm(api, order["id"], cardholder)
    fx.ticket(api, order["id"], supplier)

    invoiced = validate_success(api.get_agency_partner(agency["id"], ADMIN_HEADERS))
    assert invoiced["payable_cents"] == 36000
    assert validate_success(api.get_order(order["id"], ADMIN_HEADERS))[
        "settlement_status"
    ] == SETTLEMENT_AGENCY_INVOICED

    fx.settle(api, order["id"], 41000, settlement_adjustment_cents=-500)

    after = validate_success(api.get_agency_partner(agency["id"], ADMIN_HEADERS))
    assert after["payable_cents"] == 36500
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=800,
        points_pending_redemption=0,
        lifetime_points_redeemed=35200,
    )


def _premier_transfer_under_investigation(api):
    """A `PREMIER` account with 67,500 points, one 60,000-point transfer in flight."""
    account, cardholder = _premier_dining_account(api, 1500000)
    agreement = fx.active_agreement(
        api,
        ADMIN_HEADERS,
        APPROVER_HEADERS,
        partner_name="Aurora Skies",
        partner_program_code="AURORA",
        transfer_latency_hours=24,
        reversal_window_hours=72,
    )
    lounge = fx.grant_entitlement(
        api,
        account["id"],
        ADMIN_HEADERS,
        benefit_type=BENEFIT_LOUNGE_ACCESS,
        annual_allowance=6,
    )
    insurance = fx.grant_entitlement(
        api,
        account["id"],
        ADMIN_HEADERS,
        benefit_type=BENEFIT_TRAVEL_INSURANCE,
        annual_allowance=2,
    )
    transfer = fx.submit_transfer(
        api, account["id"], agreement["id"], 60000, cardholder
    )
    case = fx.open_case(
        api,
        account["id"],
        ANALYST_HEADERS,
        case_type=CASE_ACCOUNT_TAKEOVER,
        signals=[SIGNAL_DEVICE_CHANGE, SIGNAL_EMAIL_CHANGE],
        device_fingerprint_changed=True,
    )
    return account, transfer, case, lounge, insurance


def test_instant_score_leg_only_watches_the_account_and_leaves_the_transfer_alone(api):
    """
    "At case opening the `instant_score` is the sum of the weights of the case's
    distinct signals, capped at 100: a device change contributes 30, a new payee 25,
    an email change 20 ... While the case is `OPEN`, `risk_score` equals
    `instant_score`."

    Design: Difficulty/dual_variant_calc/dual_variant_ato_score_instant_vs_review
    """
    account, transfer, case, lounge, insurance = _premier_transfer_under_investigation(api)

    assert case["status"] == CASE_OPEN
    assert case["instant_score"] == 50
    assert case["review_score"] is None
    assert case["risk_score"] == 50

    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=7500,
        points_pending_redemption=60000,
        fraud_posture=POSTURE_WATCH,
    )
    assert fx.read_transfer(api, transfer["id"])["status"] == TRANSFER_SUBMITTED

    held_lounge = fx.read_entitlement(api, lounge["id"])
    assert held_lounge["status"] == ENTITLEMENT_SUSPENDED
    assert held_lounge["suspension_reason"] == SUSPENSION_POSTURE_WATCH
    assert fx.read_entitlement(api, insurance["id"])["status"] == ENTITLEMENT_ACTIVE


def test_review_score_leg_crosses_the_lock_threshold_the_instant_leg_did_not(api):
    """
    "`review_score` is the `instant_score` plus the velocity term less the credit,
    clamped below at 0 and above at 100. From `UNDER_REVIEW` onward `risk_score`
    equals `review_score`."

    Design: Difficulty/dual_variant_calc/dual_variant_ato_score_instant_vs_review
    """
    account, transfer, case, lounge, insurance = _premier_transfer_under_investigation(api)

    reviewed = fx.review_case(api, case["id"], ANALYST_HEADERS)
    assert reviewed["status"] == CASE_UNDER_REVIEW
    assert reviewed["instant_score"] == 50
    assert reviewed["review_score"] == 60
    assert reviewed["risk_score"] == 60

    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=67500,
        points_pending_redemption=0,
        fraud_posture=POSTURE_LOCKED,
    )

    rejected = fx.read_transfer(api, transfer["id"])
    assert rejected["status"] == TRANSFER_REJECTED
    assert rejected["resolution_reason"] == RESOLUTION_POSTURE_LOCKED

    entries = read_ledger(api, ADMIN_HEADERS, account["id"])
    assert_ledger_entry_types(
        entries, [ENTRY_EARN_BASE, ENTRY_TRANSFER_DEBIT, ENTRY_TRANSFER_REVERSAL]
    )
    assert_ledger_entry(
        entries[2],
        entry_type=ENTRY_TRANSFER_REVERSAL,
        points_delta=60000,
        balance_after=67500,
        source_entity_id=transfer["id"],
    )

    locked_insurance = fx.read_entitlement(api, insurance["id"])
    assert locked_insurance["status"] == ENTITLEMENT_SUSPENDED
    assert locked_insurance["suspension_reason"] == SUSPENSION_POSTURE_LOCKED
    watched_lounge = fx.read_entitlement(api, lounge["id"])
    assert watched_lounge["status"] == ENTITLEMENT_SUSPENDED
    assert watched_lounge["suspension_reason"] == SUSPENSION_POSTURE_WATCH
