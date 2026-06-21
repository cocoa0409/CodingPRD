"""Validation precedence, cross-entity state dependencies, resource overlap (capacity),
boundary precision, and the per-validation error catalogue.

Covers queue A priority_pair_validation_conflict, cross_entity_state_dependency,
resource_temporal_overlap, the par-boundary half of boundary_precision_check, and queue B
violation->error instances (weight gain, overpayment, release-not-due, credit-limit,
product-mismatch) plus aging.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_catalog, produce_roasted_lot, create_green_lot, create_planned_batch,
    place_order, reserve_fulfillment, ship_fulfillment, setup_shipped_order,
    issue_invoice, setup_issued_invoice, clock_set, clock_advance,
    start_roast_batch_payload, complete_roast_batch_payload,
    order_line, create_fulfillment_payload, create_standing_order_payload,
    create_payment_payload,
    TEST_USERS,
)

ROASTER = TEST_USERS["roaster_headers"]
SALES = TEST_USERS["sales_headers"]


# ─── priority_pair_validation_conflict / state_vs_fiscal_invoice_on_open_unfulfilled_order ─

def test_state_check_beats_fiscal_on_open_order_invoice(api):
    """PRD §3.6: "At least one fulfillment must have shipped — the order's
    `fulfillment_status` must be `PARTIALLY_FULFILLED` or `FULFILLED` — otherwise the order
    has shipped nothing to bill and the issue is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_invoice_on_open_unfulfilled_order
    """
    cat = setup_catalog(
        tier_overrides={"discount_bps": 0, "freshness_max_days": 60},
        account_overrides={"net_terms_days": 30, "credit_limit_cents": 1000},
        product_overrides={"base_price_cents_per_kg": 2000, "freshness_window_days": 60},
    )
    prod = cat["product"]
    # OPEN, UNBILLED order; total 20000 would also breach the 1000 credit ceiling.
    order = place_order(cat["account"]["id"], [order_line(prod["id"], 10)])
    res = api.invoice_order(order["id"], SALES)
    # State gate (priority 6) pre-empts the fiscal gate (priority 13).
    validate_error(res, "ERR_INVALID_STATE")
    order_read = validate_success(api.get_order(order["id"], SALES), 200)
    assert order_read["billing_status"] == "UNBILLED"


# ─── priority_pair_validation_conflict / safety_vs_business_constraint_stale_roast_beats_insufficient_roasted ─

def test_stale_roast_beats_insufficient_roasted(api):
    """PRD §3.8: "The remaining business checks then apply per operation — referential
    compatibility (`ERR_PRODUCT_MISMATCH`), freshness (`ERR_STALE_ROAST`), release timing
    (`ERR_RELEASE_NOT_DUE`), green sufficiency (`ERR_INSUFFICIENT_GREEN`), roasted sufficiency
    and line over-allocation (`ERR_INSUFFICIENT_ROASTED`), roast weight conservation
    (`ERR_WEIGHT_GAIN`), the credit ceiling (`ERR_CREDIT_LIMIT_EXCEEDED`), and payment sanity
    (`ERR_OVERPAYMENT`)."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_business_constraint_stale_roast_beats_insufficient_roasted
    """
    clock_set("2026-06-01T00:00:00Z")
    cat = setup_catalog(
        tier_overrides={"discount_bps": 0, "freshness_max_days": 10},
        account_overrides={"net_terms_days": 30, "credit_limit_cents": 1_000_000},
        product_overrides={"base_price_cents_per_kg": 2200, "freshness_window_days": 14},
    )
    prod = cat["product"]
    _, lot = produce_roasted_lot(prod["id"], actual_green_kg=8, actual_roasted_kg=5)
    order = place_order(cat["account"]["id"], [order_line(prod["id"], 5)])
    clock_set("2026-06-20T00:00:00Z")  # age 19 days -> stale; request 20 kg > 5 available.
    rl = validate_success(api.get_roasted_lot(lot["id"], SALES), 200)
    res = api.create_fulfillment(
        order["id"], create_fulfillment_payload(prod["id"], lot["id"], 20, rl["version"]), SALES)
    # Freshness (priority 8) pre-empts insufficient-roasted (priority 11).
    validate_error(res, "ERR_STALE_ROAST")


# ─── cross_entity_state_dependency / invoice_requires_order_shipped_cross_order_state ─

def test_invoice_blocked_when_order_open_no_shipment(api):
    """PRD §3.6: "At least one fulfillment must have shipped — the order's
    `fulfillment_status` must be `PARTIALLY_FULFILLED` or `FULFILLED` — otherwise the order
    has shipped nothing to bill and the issue is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/invoice_requires_order_shipped_cross_order_state
    """
    cat = setup_catalog(
        tier_overrides={"discount_bps": 0, "freshness_max_days": 60},
        account_overrides={"net_terms_days": 30, "credit_limit_cents": 1_000_000},
        product_overrides={"base_price_cents_per_kg": 2000, "freshness_window_days": 60},
    )
    prod = cat["product"]
    order = place_order(cat["account"]["id"], [order_line(prod["id"], 5)])
    res = api.invoice_order(order["id"], SALES)
    validate_error(res, "ERR_INVALID_STATE")
    order_read = validate_success(api.get_order(order["id"], SALES), 200)
    assert order_read["billing_status"] == "UNBILLED"


# ─── cross_entity_state_dependency / standing_release_blocked_by_account_credit_hold ─

def test_standing_release_blocked_when_account_credit_hold(api):
    """PRD §3.6: "an account that now has any `OVERDUE` invoice, or whose
    `outstanding_balance_cents` exceeds its `credit_limit_cents`, is cascaded to
    `CREDIT_HOLD`."
    PRD §3.2: "The owning account must be `ACTIVE` (not on credit hold), and the subscribed
    product must not be archived; a release against an archived product is rejected with
    `ERR_PRODUCT_MISMATCH`."

    Design: Difficulty/cross_entity_state_dependency/standing_release_blocked_by_account_credit_hold
    """
    clock_set("2026-06-01T00:00:00Z")
    cat = setup_catalog(
        tier_overrides={"discount_bps": 0, "freshness_max_days": 60},
        account_overrides={"net_terms_days": 15, "credit_limit_cents": 1_000_000},
        product_overrides={"base_price_cents_per_kg": 2000, "freshness_window_days": 60},
    )
    acct = cat["account"]
    prod = cat["product"]
    _, lot = produce_roasted_lot(prod["id"], actual_green_kg=30, actual_roasted_kg=25)
    order, _ = setup_shipped_order(acct["id"], prod["id"], lot["id"], qty_kg=10, allocated_kg=10)
    issue_invoice(order["id"])
    so = get_success_data(api.create_standing_order(
        acct["id"], create_standing_order_payload(prod["id"], "2026-06-05T00:00:00Z",
                                                  qty_kg=5, cadence_days=7), SALES))
    # Age the issued invoice past its 2026-06-16 due date -> OVERDUE -> account CREDIT_HOLD.
    clock_advance("2026-06-17T00:00:00Z")
    acct_read = validate_success(api.get_account(acct["id"], SALES), 200)
    assert acct_read["status"] == "CREDIT_HOLD"
    res = api.release_standing_order(so["id"], SALES)
    validate_error(res, "ERR_INVALID_STATE")


# ─── resource_temporal_overlap / green_reservation_aggregate_capacity_overlap ─

def test_second_start_rejected_insufficient_green(api):
    """PRD §3.3: "The `RoasterStaff` supplies the `actual_green_kg` actually charged, which
    must be greater than zero and must not exceed the green lot's current `on_hand_kg` —
    charging more green than physically on hand is rejected with `ERR_INSUFFICIENT_GREEN`."

    Design: Difficulty/resource_temporal_overlap/green_reservation_aggregate_capacity_overlap
    """
    product = setup_catalog()["product"]
    gl = create_green_lot(received_kg=30, par_level_kg=5)
    batch_a = create_planned_batch(gl["id"], product["id"], planned_green_kg=20)
    batch_b = create_planned_batch(gl["id"], product["id"], planned_green_kg=20)
    api.start_roast_batch(batch_a["id"], start_roast_batch_payload(20), ROASTER)
    # Only 10 kg physically remain on the lot after A consumed 20.
    res = api.start_roast_batch(batch_b["id"], start_roast_batch_payload(20), ROASTER)
    validate_error(res, "ERR_INSUFFICIENT_GREEN")


# ─── resource_temporal_overlap / roasted_lot_allocation_overlap_against_available ─

def test_second_reservation_rejected_insufficient_roasted(api):
    """PRD §3.5: "The lot must have enough unreserved stock: its `available_kg` must be at
    least `allocated_kg`, and the new allocation must not push the cumulative
    reserved-plus-shipped kilograms for that line's product above the line's ordered `qty_kg`;
    either shortfall is rejected with `ERR_INSUFFICIENT_ROASTED`."

    Design: Difficulty/resource_temporal_overlap/roasted_lot_allocation_overlap_against_available
    """
    cat = setup_catalog(product_overrides={"base_price_cents_per_kg": 2000,
                                            "freshness_window_days": 60})
    prod = cat["product"]
    _, lot = produce_roasted_lot(prod["id"], actual_green_kg=14, actual_roasted_kg=10)
    order_a = place_order(cat["account"]["id"], [order_line(prod["id"], 7)])
    reserve_fulfillment(order_a["id"], prod["id"], lot["id"], 7)  # available 10 -> 3
    order_b = place_order(cat["account"]["id"], [order_line(prod["id"], 5)])
    rl = validate_success(api.get_roasted_lot(lot["id"], SALES), 200)
    res = api.create_fulfillment(
        order_b["id"], create_fulfillment_payload(prod["id"], lot["id"], 5, rl["version"]), SALES)
    # Only 3.000 kg remain after the first 7 kg reservation.
    validate_error(res, "ERR_INSUFFICIENT_ROASTED")


# ─── boundary_precision_check / reorder_par_boundary_strict_less_than ───────

def test_available_equal_par_stays_ok(api):
    """PRD §2.7: "The lot's `reorder_status` is `BELOW_PAR` when `available_kg` is strictly
    less than `par_level_kg`, and `OK` otherwise; the boundary is inclusive on the safe side,
    so a lot whose available kilograms exactly equal its par level reads `OK`."

    Design: Difficulty/boundary_precision_check/reorder_par_boundary_strict_less_than
    """
    product = setup_catalog()["product"]
    gl = create_green_lot(received_kg=50, par_level_kg=25)
    batch = create_planned_batch(gl["id"], product["id"], planned_green_kg=25)
    api.start_roast_batch(batch["id"], start_roast_batch_payload(25), ROASTER)
    gl_read = validate_success(api.get_green_lot(gl["id"], ROASTER), 200)
    assert gl_read["available_kg"] == 25.000, \
        f"available should be 25.000 (50 - 25), got {gl_read['available_kg']}"
    assert gl_read["reorder_status"] == "OK", \
        f"available 25.000 == par 25 stays OK (strict <), got {gl_read['reorder_status']}"


def test_available_below_par_flips_below_par(api):
    """PRD §2.7: "The lot's `reorder_status` is `BELOW_PAR` when `available_kg` is strictly
    less than `par_level_kg`, and `OK` otherwise; the boundary is inclusive on the safe side,
    so a lot whose available kilograms exactly equal its par level reads `OK`."

    Design: Difficulty/boundary_precision_check/reorder_par_boundary_strict_less_than
    """
    product = setup_catalog()["product"]
    gl = create_green_lot(received_kg=50, par_level_kg=25)
    batch = create_planned_batch(gl["id"], product["id"], planned_green_kg=26)
    api.start_roast_batch(batch["id"], start_roast_batch_payload(26), ROASTER)
    gl_read = validate_success(api.get_green_lot(gl["id"], ROASTER), 200)
    # available 24.000 < par 25 -> BELOW_PAR (one kg past the inclusive boundary).
    assert gl_read["available_kg"] == 24.000
    assert gl_read["reorder_status"] == "BELOW_PAR", \
        f"available 24.000 < par 25 must read BELOW_PAR, got {gl_read['reorder_status']}"


# ─── validations / weight_gain_on_complete_rejected (queue B) ───────────────

def test_weight_gain_on_complete_rejected(api):
    """PRD §3.3: "A roast cannot gain weight, so `actual_roasted_kg` must not exceed the
    batch's `actual_green_kg`; a violation is rejected with `ERR_WEIGHT_GAIN`."

    Design: Corner/validations/weight_gain_on_complete_rejected
    """
    from test_helpers import cooling_batch
    product = setup_catalog()["product"]
    batch = cooling_batch(product["id"], actual_green_kg=20, planned_green_kg=20)
    res = api.complete_roast_batch(batch["id"], complete_roast_batch_payload(22), ROASTER)
    validate_error(res, "ERR_WEIGHT_GAIN")


# ─── validations / overpayment_rejected (queue B) ──────────────────────────

def test_overpayment_rejected(api):
    """PRD §3.6: "The applied amount may not exceed the invoice's current `amount_due_cents`
    — overpayment, where the amount is not within the half-open range from just above zero up
    to and including the amount due, is rejected with `ERR_OVERPAYMENT`."

    Design: Corner/validations/overpayment_rejected
    """
    ctx = setup_issued_invoice(qty_kg=10, base_price_cents_per_kg=2000, discount_bps=0)
    inv = ctx["invoice"]
    assert inv["amount_cents"] == 20000
    res = api.create_payment(inv["id"], create_payment_payload(25000), SALES)
    validate_error(res, "ERR_OVERPAYMENT")


# ─── validations / release_not_due_rejected (queue B) ──────────────────────

def test_release_before_next_release_at_rejected(api):
    """PRD §3.2: "Releasing also requires that the logical clock has reached or passed
    `next_release_at`; releasing before then is rejected with `ERR_RELEASE_NOT_DUE`."

    Design: Corner/validations/release_not_due_rejected
    """
    clock_set("2026-06-01T00:00:00Z")
    cat = setup_catalog(product_overrides={"base_price_cents_per_kg": 2000,
                                            "freshness_window_days": 60})
    so = get_success_data(api.create_standing_order(
        cat["account"]["id"],
        create_standing_order_payload(cat["product"]["id"], "2026-06-10T00:00:00Z",
                                      qty_kg=5, cadence_days=14), SALES))
    res = api.release_standing_order(so["id"], SALES)
    validate_error(res, "ERR_RELEASE_NOT_DUE")


# ─── errors / credit_limit_exceeded_at_invoice (queue B) ───────────────────

def test_credit_limit_exceeded_at_invoice(api):
    """PRD §3.6: "If the account is on `CREDIT_HOLD` or the projected balance would exceed
    the ceiling, the issue is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Corner/errors/credit_limit_exceeded_at_invoice
    """
    cat = setup_catalog(
        tier_overrides={"discount_bps": 0, "freshness_max_days": 60},
        account_overrides={"net_terms_days": 30, "credit_limit_cents": 200000},
        product_overrides={"base_price_cents_per_kg": 2000, "freshness_window_days": 60},
    )
    acct = cat["account"]
    prod = cat["product"]
    _, lot = produce_roasted_lot(prod["id"], actual_green_kg=130, actual_roasted_kg=110)
    order1, _ = setup_shipped_order(acct["id"], prod["id"], lot["id"], qty_kg=75, allocated_kg=75)
    issue_invoice(order1["id"])  # posted balance 150000
    order2, _ = setup_shipped_order(acct["id"], prod["id"], lot["id"], qty_kg=30, allocated_kg=30)
    # 150000 + 60000 = 210000 > 200000 limit.
    res = api.invoice_order(order2["id"], SALES)
    validate_error(res, "ERR_CREDIT_LIMIT_EXCEEDED")
    order2_read = validate_success(api.get_order(order2["id"], SALES), 200)
    assert order2_read["billing_status"] == "UNBILLED"


# ─── errors / product_mismatch_on_fulfillment (queue B) ────────────────────

def test_product_mismatch_on_fulfillment(api):
    """PRD §3.5: "The roasted lot's `product_id` must equal the fulfillment's `product_id` —
    you cannot ship the wrong coffee — or the reservation is rejected with
    `ERR_PRODUCT_MISMATCH`."

    Design: Corner/errors/product_mismatch_on_fulfillment
    """
    profile = get_success_data(api.create_roast_profile(
        {"name": "PM", "roast_level": "MEDIUM", "expected_shrink_bps": 1500,
         "charge_temp_c": 205}, ROASTER))
    prod_a = get_success_data(api.create_product(
        {"sku": "SKU-PMA", "name": "Prod A", "roast_profile_id": profile["id"],
         "base_price_cents_per_kg": 2000, "freshness_window_days": 60}, ROASTER))
    prod_b = get_success_data(api.create_product(
        {"sku": "SKU-PMB", "name": "Prod B", "roast_profile_id": profile["id"],
         "base_price_cents_per_kg": 2100, "freshness_window_days": 60}, ROASTER))
    tier = get_success_data(api.create_price_tier(
        {"code": "PM0", "discount_bps": 0, "min_monthly_kg": 0, "freshness_max_days": 60}, SALES))
    acct = get_success_data(api.create_account(
        {"name": "Mismatch Co", "price_tier_id": tier["id"], "net_terms_days": 30,
         "credit_limit_cents": 1_000_000}, SALES))
    _, lot_a = produce_roasted_lot(prod_a["id"], actual_green_kg=30, actual_roasted_kg=25)
    order = place_order(acct["id"], [order_line(prod_b["id"], 5)])
    rl = validate_success(api.get_roasted_lot(lot_a["id"], SALES), 200)
    res = api.create_fulfillment(
        order["id"], create_fulfillment_payload(prod_b["id"], lot_a["id"], 5, rl["version"]), SALES)
    validate_error(res, "ERR_PRODUCT_MISMATCH")


# ─── cross_cutting_complexity_layers / aging_sweep_flips_overdue_and_credit_hold (queue B) ─

def test_aging_sweep_flips_overdue_and_credit_hold(api):
    """PRD §3.6: "any invoice that is `ISSUED` or `PARTIALLY_PAID`, whose pinned `due_at` the
    clock has now passed (the clock is strictly later than `due_at`), and which still has a
    positive `amount_due_cents`, is moved to `OVERDUE`. As a consequence of aging, an account
    that now has any `OVERDUE` invoice, or whose `outstanding_balance_cents` exceeds its
    `credit_limit_cents`, is cascaded to `CREDIT_HOLD`."

    Design: Corner/cross_cutting_complexity_layers/aging_sweep_flips_overdue_and_credit_hold
    """
    clock_set("2026-06-01T00:00:00Z")
    ctx = setup_issued_invoice(qty_kg=10, base_price_cents_per_kg=2000, discount_bps=0,
                               net_terms_days=15)
    inv = ctx["invoice"]
    acct = ctx["account"]
    clock_advance("2026-06-20T00:00:00Z")  # past due 2026-06-16
    inv_read = validate_success(api.get_invoice(inv["id"], SALES), 200)
    assert inv_read["status"] == "OVERDUE"
    acct_read = validate_success(api.get_account(acct["id"], SALES), 200)
    assert acct_read["status"] == "CREDIT_HOLD"


# ─── Second tests for queue-A instances needing >=2 coverage ────────────────

def test_partially_fulfilled_order_can_be_invoiced(api):
    """PRD §3.6: "At least one fulfillment must have shipped — the order's
    `fulfillment_status` must be `PARTIALLY_FULFILLED` or `FULFILLED`".

    Positive companion: once a shipment has bubbled the order to PARTIALLY_FULFILLED the
    billing transition is permitted, confirming the cross-order-state precondition is the
    gate (not, e.g., full fulfillment).

    Design: Difficulty/cross_entity_state_dependency/invoice_requires_order_shipped_cross_order_state
    """
    cat = setup_catalog(
        tier_overrides={"discount_bps": 0, "freshness_max_days": 60},
        account_overrides={"net_terms_days": 30, "credit_limit_cents": 1_000_000},
        product_overrides={"base_price_cents_per_kg": 2000, "freshness_window_days": 60},
    )
    prod = cat["product"]
    _, lot = produce_roasted_lot(prod["id"], actual_green_kg=30, actual_roasted_kg=25)
    order = place_order(cat["account"]["id"], [order_line(prod["id"], 10)])
    ful = reserve_fulfillment(order["id"], prod["id"], lot["id"], 6)
    ship_fulfillment(ful["id"])
    order_read = validate_success(api.get_order(order["id"], SALES), 200)
    assert order_read["fulfillment_status"] == "PARTIALLY_FULFILLED"
    issue_invoice(order["id"])
    after = validate_success(api.get_order(order["id"], SALES), 200)
    assert after["billing_status"] == "INVOICED", \
        "a PARTIALLY_FULFILLED order satisfies the cross-order-state precondition for billing"


def test_standing_release_succeeds_while_account_active(api):
    """PRD §3.2: "The owning account must be `ACTIVE` (not on credit hold)".
    PRD §3.2: "When all of these hold, the release creates a new order for the account with a
    single line for the standing order's `product_id` and `qty_kg`".

    Negative-companion's mirror: with the account ACTIVE the same release that the credit-hold
    case rejects is permitted, isolating account status as the cross-entity gate.

    Design: Difficulty/cross_entity_state_dependency/standing_release_blocked_by_account_credit_hold
    """
    clock_set("2026-06-01T00:00:00Z")
    cat = setup_catalog(product_overrides={"base_price_cents_per_kg": 2000,
                                            "freshness_window_days": 60})
    acct = cat["account"]
    prod = cat["product"]
    so = get_success_data(api.create_standing_order(
        acct["id"], create_standing_order_payload(prod["id"], "2026-06-05T00:00:00Z",
                                                  qty_kg=5, cadence_days=7), SALES))
    acct_read = validate_success(api.get_account(acct["id"], SALES), 200)
    assert acct_read["status"] == "ACTIVE"
    clock_set("2026-06-06T00:00:00Z")  # at/after next_release_at, no overdue invoice
    order = validate_success(api.release_standing_order(so["id"], SALES), 201)
    assert order["standing_order_id"] == so["id"], \
        "the released order records its originating standing order"


def test_stale_roast_alone_rejected_with_sufficient_stock(api):
    """PRD §3.5: "an age equal to the ceiling is still eligible, while an age one day beyond
    it is stale and the reservation is rejected with `ERR_STALE_ROAST`."

    Isolates the higher-priority freshness gate: ample stock is present (no insufficient-roasted
    confound), so the stale-roast rejection is unambiguous.

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_business_constraint_stale_roast_beats_insufficient_roasted
    """
    clock_set("2026-06-01T00:00:00Z")
    cat = setup_catalog(
        tier_overrides={"discount_bps": 0, "freshness_max_days": 10},
        account_overrides={"net_terms_days": 30, "credit_limit_cents": 1_000_000},
        product_overrides={"base_price_cents_per_kg": 2200, "freshness_window_days": 14},
    )
    prod = cat["product"]
    _, lot = produce_roasted_lot(prod["id"], actual_green_kg=30, actual_roasted_kg=25)
    order = place_order(cat["account"]["id"], [order_line(prod["id"], 5)])
    clock_set("2026-06-20T00:00:00Z")  # age 19 > min(14, 10) = 10 -> stale; 5 kg <= 25 available
    rl = validate_success(api.get_roasted_lot(lot["id"], SALES), 200)
    res = api.create_fulfillment(
        order["id"], create_fulfillment_payload(prod["id"], lot["id"], 5, rl["version"]), SALES)
    validate_error(res, "ERR_STALE_ROAST")


def test_open_order_credit_breach_reports_state_not_fiscal_after_setup(api):
    """PRD §3.6: "The order must still be `UNBILLED`, or the request is rejected with
    `ERR_INVALID_STATE`. At least one fulfillment must have shipped — the order's
    `fulfillment_status` must be `PARTIALLY_FULFILLED` or `FULFILLED` — otherwise the order
    has shipped nothing to bill and the issue is rejected with `ERR_INVALID_STATE`."

    Second instance with a different ceiling magnitude (order total far exceeds the tiny
    credit limit, yet the issue is still state-blocked) confirming the state gate wins
    regardless of the fiscal margin.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_invoice_on_open_unfulfilled_order
    """
    cat = setup_catalog(
        tier_overrides={"discount_bps": 0, "freshness_max_days": 60},
        account_overrides={"net_terms_days": 30, "credit_limit_cents": 100},
        product_overrides={"base_price_cents_per_kg": 2000, "freshness_window_days": 60},
    )
    prod = cat["product"]
    order = place_order(cat["account"]["id"], [order_line(prod["id"], 50)])  # total 100000 >> 100
    res = api.invoice_order(order["id"], SALES)
    validate_error(res, "ERR_INVALID_STATE")


def test_green_start_within_on_hand_succeeds(api):
    """PRD §3.3: "The `RoasterStaff` supplies the `actual_green_kg` actually charged, which
    must be greater than zero and must not exceed the green lot's current `on_hand_kg`".

    Positive companion to the aggregate-capacity overlap: a start charging exactly the
    remaining on_hand succeeds, pinning the boundary of the green sufficiency rule.

    Design: Difficulty/resource_temporal_overlap/green_reservation_aggregate_capacity_overlap
    """
    product = setup_catalog()["product"]
    gl = create_green_lot(received_kg=30, par_level_kg=5)
    batch_a = create_planned_batch(gl["id"], product["id"], planned_green_kg=20)
    batch_b = create_planned_batch(gl["id"], product["id"], planned_green_kg=20)
    api.start_roast_batch(batch_a["id"], start_roast_batch_payload(20), ROASTER)
    # 10 kg remain on hand; charging exactly 10 is within on_hand and succeeds.
    started = validate_success(
        api.start_roast_batch(batch_b["id"], start_roast_batch_payload(10), ROASTER), 200)
    assert started["status"] == "ROASTING"


def test_reservation_within_available_succeeds(api):
    """PRD §3.5: "The lot must have enough unreserved stock: its `available_kg` must be at
    least `allocated_kg`".

    Positive companion to the per-allocation overlap: a second reservation for exactly the
    remaining available kilograms succeeds, pinning the boundary of the roasted sufficiency
    rule.

    Design: Difficulty/resource_temporal_overlap/roasted_lot_allocation_overlap_against_available
    """
    cat = setup_catalog(product_overrides={"base_price_cents_per_kg": 2000,
                                            "freshness_window_days": 60})
    prod = cat["product"]
    _, lot = produce_roasted_lot(prod["id"], actual_green_kg=14, actual_roasted_kg=10)
    order_a = place_order(cat["account"]["id"], [order_line(prod["id"], 7)])
    reserve_fulfillment(order_a["id"], prod["id"], lot["id"], 7)  # available 10 -> 3
    order_b = place_order(cat["account"]["id"], [order_line(prod["id"], 3)])
    rl = validate_success(api.get_roasted_lot(lot["id"], SALES), 200)
    ful = validate_success(api.create_fulfillment(
        order_b["id"],
        create_fulfillment_payload(prod["id"], lot["id"], 3, rl["version"]), SALES), 201)
    assert ful["status"] == "RESERVED", \
        "reserving exactly the 3.000 kg remaining must succeed"
