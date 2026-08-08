"""Financial and warranty calculations: dual-variant refund, the warranty-bonus
combinatorial formula, and the pinned per-component settlement rounding order.
"""
from test_helpers import (
    validate_success, make_concierge_headers,
    setup_refund_claim_under_review, setup_household_with_active_subscription,
    new_product, set_clock, resolution_for_claim,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _approve_and_get_resolution(api, claim_id, approver="cx-approver"):
    validate_success(api.approve_claim(claim_id, make_concierge_headers(approver)), 200)
    return resolution_for_claim(claim_id)


# ─── Difficulty: dual-variant refund (financial domain) ───────────────────────
def test_refund_prorated_variant_selected_for_basic(api):
    """PRD 3.7: "For a tier that prorates — `BASIC` — the `refund_variant` is
    `PRORATED` and the refund is the purchase price scaled by the fraction of warranty
    still remaining."

    Design: Difficulty/dual_variant_calc/refund_prorated_vs_full_financial_domain
    """
    ctx = setup_refund_claim_under_review(tier="BASIC", purchase_price_cents=100000,
                                          warranty_months=24, purchase_date="2025-01-01T00:00:00Z",
                                          clock="2026-01-01T00:00:00Z", reviewer_id="cx-reviewer")
    res = _approve_and_get_resolution(api, ctx["claim"]["id"])
    assert res["mode"] == "REFUND"
    assert res["refund_variant"] == "PRORATED"


def test_refund_prorated_amount_is_half_price(api):
    """PRD 3.7: "sets `refund_amount_cents` to the `purchase_price_cents` multiplied by
    remaining days divided by total days, rounded half-up to a whole cent."

    Design: Difficulty/dual_variant_calc/refund_prorated_vs_full_financial_domain
    """
    ctx = setup_refund_claim_under_review(tier="BASIC", purchase_price_cents=100000,
                                          warranty_months=24, purchase_date="2025-01-01T00:00:00Z",
                                          clock="2026-01-01T00:00:00Z", reviewer_id="cx-reviewer")
    res = _approve_and_get_resolution(api, ctx["claim"]["id"])
    assert res["refund_amount_cents"] == 50000


# ─── Difficulty: combinatorial warranty-bonus formula (mode a) ────────────────
def test_warranty_bonus_extends_expiry_date(api):
    """PRD 3.3: "The `warranty_expires_at` is then the `purchase_date` advanced by that
    effective number of calendar months; when the target month has no matching day, the
    date is clamped to the last day of that month."

    Design: Difficulty/combinatorial_formula/warranty_coverage_bonus_extends_mode_a
    """
    ctx = setup_household_with_active_subscription(tier="PLUS")
    prod = new_product(ctx["hh"]["id"], ctx["owner"]["id"], ctx["mfr"]["id"],
                       model_number="FR-1", serial_number=5,
                       purchase_date="2025-01-01T00:00:00Z", purchase_price_cents=80000,
                       warranty_months=12)
    set_clock("2026-06-01T00:00:00Z")
    fetched = validate_success(api.get_product(prod["id"], ADMIN), 200)
    assert fetched["warranty_expires_at"][:10] == "2026-07-01"


def test_warranty_bonus_keeps_product_under_warranty(api):
    """PRD 3.3: "otherwise, if the current clock is on or before `warranty_expires_at`
    the status is `UNDER_WARRANTY` (a product exactly at its expiry instant is still
    covered); otherwise it is `EXPIRED`."

    Design: Difficulty/combinatorial_formula/warranty_coverage_bonus_extends_mode_a
    """
    ctx = setup_household_with_active_subscription(tier="PLUS")
    prod = new_product(ctx["hh"]["id"], ctx["owner"]["id"], ctx["mfr"]["id"],
                       model_number="FR-1", serial_number=5,
                       purchase_date="2025-01-01T00:00:00Z", purchase_price_cents=80000,
                       warranty_months=12)
    set_clock("2026-06-01T00:00:00Z")
    fetched = validate_success(api.get_product(prod["id"], ADMIN), 200)
    assert fetched["coverage_status"] == "UNDER_WARRANTY"


# ─── Difficulty: settlement per-component rounding (mode b) ───────────────────
def test_settlement_components_rounded_independently(api):
    """PRD 3.8: "The shipping-reimbursement component, stored as
    `shipping_reimbursement_cents`, is the resolution's `shipping_cost_cents` multiplied
    by the tier's shipping-reimbursement fraction — 0% for `BASIC`, 50% for `PLUS`, 100%
    for `PREMIUM` — rounded half-up to a whole cent on its own."
    PRD 3.8: "The concierge-fee component, stored as `concierge_fee_cents`, is the
    `refund_amount_cents` multiplied by the tier's concierge-fee fraction — 10% for
    `BASIC`, 5% for `PLUS`, 0% for `PREMIUM` — likewise rounded half-up to a whole cent
    on its own."

    Design: Difficulty/combinatorial_formula/settlement_round_per_component_mode_b
    """
    ctx = setup_refund_claim_under_review(tier="PLUS", purchase_price_cents=100008,
                                          warranty_months=24, shipping_cost_cents=4501,
                                          reviewer_id="cx-reviewer")
    res = _approve_and_get_resolution(api, ctx["claim"]["id"])
    assert res["refund_amount_cents"] == 100008
    assert res["shipping_reimbursement_cents"] == 2251
    assert res["concierge_fee_cents"] == 5000


def test_settlement_total_uses_rounded_components(api):
    """PRD 3.8: "The `settlement_total_cents` is then the refund component plus the
    shipping-reimbursement component minus the concierge-fee component. Each piece is
    rounded before the addition and subtraction, never summed as raw products and
    rounded once at the end."

    Design: Difficulty/combinatorial_formula/settlement_round_per_component_mode_b
    """
    ctx = setup_refund_claim_under_review(tier="PLUS", purchase_price_cents=100008,
                                          warranty_months=24, shipping_cost_cents=4501,
                                          reviewer_id="cx-reviewer")
    res = _approve_and_get_resolution(api, ctx["claim"]["id"])
    assert res["settlement_total_cents"] == 97259


# ─── Corner: FULL refund variant on PLUS tier ─────────────────────────────────
def test_refund_full_variant_plus_tier(api):
    """PRD 3.7: "For a tier that does not prorate refunds — `PLUS` and `PREMIUM` — the
    `refund_variant` is `FULL` and the `refund_amount_cents` equals the product's full
    `purchase_price_cents`, regardless of how much warranty has elapsed."

    Design: Corner/calculations/refund_full_variant_plus_tier
    """
    ctx = setup_refund_claim_under_review(tier="PLUS", purchase_price_cents=100000,
                                          warranty_months=24, reviewer_id="cx-reviewer")
    res = _approve_and_get_resolution(api, ctx["claim"]["id"])
    assert res["refund_variant"] == "FULL"
    assert res["refund_amount_cents"] == 100000
