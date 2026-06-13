"""Storage accrual variants, the release-fee breakdown, the waiver tiered cap,
and the auction proceeds waterfall.

Covers difficulty queue rules: dual_variant_calc, combinatorial_formula,
boundary_precision (storage day boundary); and corner calculations/endpoints.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    assert_tow_order_money_invariants,
    assert_auction_conservation,
    TEST_USERS,
    create_impound_lot_payload,
    create_tow_order_payload,
    create_inventory_item_payload,
    set_clock,
    create_lot,
    create_order,
    add_inventory,
    create_stored_order,
    create_stored_lien_order,
    file_and_review_waiver,
    setup_open_auction_with_swept_order,
)

OP = TEST_USERS["lot_operator_headers"]
CLAIMANT = TEST_USERS["claimant_headers"]
AUCTION = TEST_USERS["auction_official_headers"]


# ─── dual_variant_calc / storage_estimate_vs_accrued_diverge ──────────────────
def test_estimate_and_accrued_storage_diverge_after_five_days(api):
    """PRD §3.3: "it is the lot's daily_storage_rate_cents multiplied by the lot's
    statutory_hold_days, ignoring how much time actually elapses."
    PRD §2.9: "The order's reported accrued_days and accrued_storage_cents are
    always derived by summing days_counted and segment_charge_cents across these
    segments, so that freezing and resuming accrual never double-counts a day at
    the boundary."

    Design: Difficulty/dual_variant_calc/storage_estimate_vs_accrued_diverge
    """
    set_clock("2026-01-01T00:00:00Z")
    lot, order = create_stored_order(
        lot_overrides={"daily_storage_rate_cents": 5000, "statutory_hold_days": 30},
        order_overrides={"tow_type": "POLICE"},
    )
    set_clock("2026-01-06T00:00:00Z")  # exactly 5 days stored
    refreshed = validate_success(api.get_tow_order(order["id"], OP), 200)
    assert refreshed["estimated_storage_cents"] == 150000, "ESTIMATE = 5000 * 30"
    assert refreshed["accrued_storage_cents"] == 25000, "ACCRUED = 5 days * 5000"
    assert refreshed["estimated_storage_cents"] != refreshed["accrued_storage_cents"]


def test_estimate_fixed_at_intake_independent_of_elapsed_time(api):
    """PRD §3.3: "the system fixes the order's estimated_storage_cents, a
    forward-looking ESTIMATE projection computed once and never re-counted: it is
    the lot's daily_storage_rate_cents multiplied by the lot's statutory_hold_days,
    ignoring how much time actually elapses."

    Design: Difficulty/dual_variant_calc/storage_estimate_vs_accrued_diverge
    """
    set_clock("2026-02-01T00:00:00Z")
    lot, order = create_stored_order(
        lot_overrides={"daily_storage_rate_cents": 5000, "statutory_hold_days": 30},
        order_overrides={"tow_type": "POLICE"},
    )
    assert order["estimated_storage_cents"] == 150000
    set_clock("2026-02-20T00:00:00Z")  # 19 days later: estimate must not move
    refreshed = validate_success(api.get_tow_order(order["id"], OP), 200)
    assert refreshed["estimated_storage_cents"] == 150000


# ─── combinatorial_formula / release_fee_per_component_round_then_sum ──────────
def test_balance_due_is_sum_of_storage_admin_lien_components(api):
    """PRD §3.5: "The order's balance_due_cents is the sum of those three components."
    PRD §3.5: "The third is a lien-processing charge equal to the lot's
    lien_processing_fee_cents when the order has a lienholder_id on record, and zero
    when it does not."

    Design: Difficulty/combinatorial_formula/release_fee_per_component_round_then_sum
    """
    set_clock("2026-02-01T00:00:00Z")
    lot, lh, order = create_stored_lien_order(
        lot_overrides={"daily_storage_rate_cents": 5000, "admin_fee_cents": 7500,
                       "lien_processing_fee_cents": 3000},
    )
    set_clock("2026-02-06T00:00:00Z")  # 5 days
    refreshed = validate_success(api.get_tow_order(order["id"], OP), 200)
    assert refreshed["accrued_storage_cents"] == 25000
    assert refreshed["balance_due_cents"] == 35500, "25000 storage + 7500 admin + 3000 lien"
    assert_tow_order_money_invariants(refreshed)


def test_balance_due_omits_lien_component_without_lienholder(api):
    """PRD §3.5: "a lien-processing charge equal to the lot's lien_processing_fee_cents
    when the order has a lienholder_id on record, and zero when it does not."

    Design: Difficulty/combinatorial_formula/release_fee_per_component_round_then_sum
    """
    set_clock("2026-02-01T00:00:00Z")
    lot, order = create_stored_order(
        lot_overrides={"daily_storage_rate_cents": 5000, "admin_fee_cents": 7500,
                       "lien_processing_fee_cents": 3000},
        order_overrides={"tow_type": "POLICE"},
    )
    set_clock("2026-02-06T00:00:00Z")  # 5 days, no lien
    refreshed = validate_success(api.get_tow_order(order["id"], OP), 200)
    assert refreshed["balance_due_cents"] == 32500, "25000 storage + 7500 admin + 0 lien"


# ─── combinatorial_formula / waiver_credit_tier_keyed_on_pre_waiver_balance ───
def test_waiver_cap_uses_pre_waiver_tier_and_floors_net_due(api):
    """PRD §3.6: "a balance from 50000 cents up to but not including 150000 cents
    permits a cap of 50 percent"
    PRD §3.6: "the cap in cents is the pre-waiver balance multiplied by the cap
    percentage and divided by 100, with the result rounded down to a whole cent.
    Fourth, the approved_amount_cents is the smaller of the claimant's
    requested_amount_cents and that computed cap."

    Design: Difficulty/combinatorial_formula/waiver_credit_tier_keyed_on_pre_waiver_balance
    """
    set_clock("2026-03-01T00:00:00Z")
    lot, lh, order = create_stored_lien_order(
        lot_overrides={"daily_storage_rate_cents": 5000, "admin_fee_cents": 7500,
                       "lien_processing_fee_cents": 3000},
    )
    set_clock("2026-03-21T00:00:00Z")  # 20 days -> 100000 storage + 7500 + 3000 = 110500 (tier2 50%)
    waiver = file_and_review_waiver(order["id"], filer_user_id="claimant-1",
                                    reason="BILLING_DISPUTE", requested_amount_cents=80000)
    res = api.approve_waiver(order["id"], waiver["id"], TEST_USERS["lot_operator_headers"])
    approved = validate_success(res, 200)
    assert approved["approved_amount_cents"] == 55250, "cap = floor(110500 * 50 / 100) = 55250"
    refreshed = validate_success(api.get_tow_order(order["id"], OP), 200)
    assert refreshed["net_due_cents"] == 55250, "110500 - 55250"


def test_waiver_request_below_cap_approves_full_request(api):
    """PRD §3.6: "the approved_amount_cents is the smaller of the claimant's
    requested_amount_cents and that computed cap."
    PRD §3.6: "a balance below 50000 cents permits a cap of 100 percent (a full waiver)"

    Design: Difficulty/combinatorial_formula/waiver_credit_tier_keyed_on_pre_waiver_balance
    """
    set_clock("2027-08-01T00:00:00Z")
    lot, lh, order = create_stored_lien_order(
        lot_overrides={"daily_storage_rate_cents": 5000, "admin_fee_cents": 7500,
                       "lien_processing_fee_cents": 3000},
    )
    set_clock("2027-08-06T00:00:00Z")  # 5 days -> 25000 + 7500 + 3000 = 35500 (tier1, cap 100%)
    waiver = file_and_review_waiver(order["id"], filer_user_id="claimant-t1",
                                    reason="HARDSHIP", requested_amount_cents=20000)
    res = api.approve_waiver(order["id"], waiver["id"], TEST_USERS["lot_operator_headers"])
    approved = validate_success(res, 200)
    assert approved["approved_amount_cents"] == 20000, "request 20000 < cap 35500"
    refreshed = validate_success(api.get_tow_order(order["id"], OP), 200)
    assert refreshed["net_due_cents"] == 15500, "35500 - 20000"


# ─── Corner: calculations / tier1_full_waiver_under_threshold ─────────────────
def test_tier1_full_waiver_cap_below_threshold(api):
    """PRD §3.6: "a balance below 50000 cents permits a cap of 100 percent (a full waiver)"
    PRD §3.6: "the approved_amount_cents is the smaller of the claimant's
    requested_amount_cents and that computed cap."

    Design: Corner/calculations/tier1_full_waiver_under_threshold
    """
    set_clock("2027-08-01T00:00:00Z")
    lot, lh, order = create_stored_lien_order(
        lot_overrides={"daily_storage_rate_cents": 5000, "admin_fee_cents": 7500,
                       "lien_processing_fee_cents": 3000},
    )
    set_clock("2027-08-06T00:00:00Z")  # balance 35500
    waiver = file_and_review_waiver(order["id"], filer_user_id="claimant-t1",
                                    reason="HARDSHIP", requested_amount_cents=20000)
    res = api.approve_waiver(order["id"], waiver["id"], TEST_USERS["lot_operator_headers"])
    approved = validate_success(res, 200)
    assert approved["approved_amount_cents"] == 20000
    refreshed = validate_success(api.get_tow_order(order["id"], OP), 200)
    assert refreshed["net_due_cents"] == 15500


# ─── boundary_precision / storage_day_boundary_exactly_24h_counts_one_day ─────
def test_exactly_24_hours_counts_as_one_storage_day(api):
    """PRD §2.6: "The day boundary is strict on hours: a span of exactly 24.0 hours
    counts as 1 day, while a span of 24.01 hours counts as 2 days, because any
    fraction of a day beyond a completed day rolls into a full additional day."

    Design: Difficulty/boundary_precision_check/storage_day_boundary_exactly_24h_counts_one_day
    """
    set_clock("2026-09-01T00:00:00Z")
    lot, order = create_stored_order(
        lot_overrides={"daily_storage_rate_cents": 5000},
        order_overrides={"tow_type": "POLICE"},
    )
    set_clock("2026-09-02T00:00:00Z")  # exactly 24.0 hours
    refreshed = validate_success(api.get_tow_order(order["id"], OP), 200)
    assert refreshed["accrued_days"] == 1, "ceil(24/24) == 1, not 2"
    assert refreshed["accrued_storage_cents"] == 5000


def test_just_over_24_hours_counts_as_two_storage_days(api):
    """PRD §2.6: "a span of exactly 24.0 hours counts as 1 day, while a span of
    24.01 hours counts as 2 days, because any fraction of a day beyond a completed
    day rolls into a full additional day."

    Design: Difficulty/boundary_precision_check/storage_day_boundary_exactly_24h_counts_one_day
    """
    set_clock("2026-09-01T00:00:00Z")
    lot, order = create_stored_order(
        lot_overrides={"daily_storage_rate_cents": 5000},
        order_overrides={"tow_type": "POLICE"},
    )
    set_clock("2026-09-02T00:30:00Z")  # 24.5 hours -> ceil = 2
    refreshed = validate_success(api.get_tow_order(order["id"], OP), 200)
    assert refreshed["accrued_days"] == 2
    assert refreshed["accrued_storage_cents"] == 10000


# ─── Corner: calculations / waterfall_remainder_to_owner_surplus ──────────────
def test_proceeds_waterfall_splits_sale_into_lot_lien_surplus(api):
    """PRD §3.9: "the lot recovery is the smaller of the sale_price_cents and the
    sum of that order's accrued_storage_cents and the lot's admin_fee_cents. The
    lien payoff is then the smaller of whatever remains and the lot's
    lien_processing_fee_cents if the order has a lienholder, or zero if it does not.
    The surplus to the owner is whatever remains after those two buckets, floored at zero."

    Design: Corner/calculations/waterfall_remainder_to_owner_surplus
    """
    lot, lh, order, auction = setup_open_auction_with_swept_order(
        intake_iso="2027-07-01T00:00:00Z",
        eligible_iso="2027-07-06T00:00:00Z",
        window_start="2027-07-06T00:00:00Z",
        window_end="2027-07-06T06:00:00Z",
        lot_overrides={"daily_storage_rate_cents": 5000, "admin_fee_cents": 7500,
                       "lien_processing_fee_cents": 3000, "statutory_hold_days": 3,
                       "notice_grace_days": 0},
        with_lien=True,
    )
    res = api.record_sale(auction["id"], {"tow_order_id": order["id"], "sale_price_cents": 40000}, AUCTION)
    validate_success(res, 200)
    auc = validate_success(api.get_auction(auction["id"], AUCTION), 200)
    assert auc["gross_proceeds_cents"] == 40000
    assert auc["distributed_cents"] == 32500, "lot recovery min(40000, 25000+7500)"
    assert auc["lien_payoff_cents"] == 3000
    assert auc["surplus_to_owner_cents"] == 4500
    assert_auction_conservation(auc)


# ─── Corner: endpoints / payment_increments_amount_paid ───────────────────────
def test_payments_accumulate_amount_paid_cents(api):
    """PRD §3.5: "A Claimant or a LotOperator can record a payment toward the
    balance, supplying amount_cents; each recorded payment adds amount_cents to the
    order's amount_paid_cents."

    Design: Corner/endpoints/payment_increments_amount_paid
    """
    lot, order = create_stored_order(order_overrides={"tow_type": "POLICE"})
    api.record_payment(order["id"], {"amount_cents": 10000}, TEST_USERS["claimant_headers"])
    res = api.record_payment(order["id"], {"amount_cents": 5000}, TEST_USERS["claimant_headers"])
    updated = validate_success(res, 200)
    assert updated["amount_paid_cents"] == 15000, "10000 + 5000 cumulative"


# ─── Corner: consistency_model / immediate_visibility_of_accrual_on_read ──────
def test_accrual_visible_immediately_on_read(api):
    """PRD §2.9: "The order's reported accrued_days and accrued_storage_cents are
    always derived by summing days_counted and segment_charge_cents across these segments"
    PRD §2.4: "from that point forward every reading of the current time — for
    accrual, for grace-window checks, for offer-expiry checks — uses the set value."

    Design: Corner/consistency_model/immediate_visibility_of_accrual_on_read
    """
    set_clock("2028-03-01T00:00:00Z")
    lot, order = create_stored_order(
        lot_overrides={"daily_storage_rate_cents": 5000},
        order_overrides={"tow_type": "POLICE"},
    )
    set_clock("2028-03-06T00:00:00Z")  # 5 days
    refreshed = validate_success(api.get_tow_order(order["id"], OP), 200)
    assert refreshed["accrued_storage_cents"] == 25000
