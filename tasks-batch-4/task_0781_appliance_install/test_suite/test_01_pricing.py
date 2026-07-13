"""Pricing: dual-variant quote/final divergence, combinatorial final-price formula,
per-line parts rounding, provisional/final payout, and the schedule-time quote."""
from test_helpers import (
    validate_success, PayoutStatus, WorkOrderStatus,
    setup_scheduled_order, setup_completed_order,
    request_redo, dispatch_order, offered_assignment_for, accept_assignment,
    start_order, complete_order, close_order, set_clock, payout_for,
)


# Rich divergent order: base 12000, 3 add-ons (3000+2500+2000), 2 parts, after-hours 20:00-21:00.
RICH_ADDONS = [3000, 2500, 2000]
RICH_PARTS = [
    {"name": "Bracket", "unit_cost_cents": 1500, "quantity": 2, "markup_bps": 2000},
    {"name": "HDMI", "unit_cost_cents": 800, "quantity": 1, "markup_bps": 5000},
]


def _rich_completed(api):
    return setup_completed_order(
        api, base_price_cents=12000, commission_rate_bps=1000, warranty_days=30,
        scheduled_start="2026-03-05T20:00:00Z", scheduled_end="2026-03-05T21:00:00Z",
        addon_prices=RICH_ADDONS, parts=RICH_PARTS, clock="2026-03-05T21:30:00Z")


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/workorder_quoted_vs_final_price_diverge
# ---------------------------------------------------------------------------
def test_final_price_diverges_from_quoted_price(api):
    """PRD §3.6: "The `final_price_cents` is then the install task's `base_price_cents` plus the
    discounted add-ons total plus the billed parts total plus the zone surcharge. Because this
    final figure folds in a possible discount, billed parts, and a surcharge, it diverges from the
    earlier `quoted_price_cents` whenever any of those three is present."

    Design: Difficulty/dual_variant_calc/workorder_quoted_vs_final_price_diverge
    """
    ctx = _rich_completed(api)
    wo = ctx["wo"]
    assert wo["final_price_cents"] == 27550, f"expected final 27550, got {wo['final_price_cents']}"
    assert wo["final_price_cents"] != wo["quoted_price_cents"], "final must diverge from quote"


def test_quoted_price_is_provisional_estimate_only(api):
    """PRD §3.3: "The `quoted_price_cents` is the install task's `base_price_cents` plus the sum of
    the `price_cents` of every add-on named in `selected_addon_ids`, at full list price — with no
    bundle discount, no parts, and no zone surcharge folded in."

    Design: Difficulty/dual_variant_calc/workorder_quoted_vs_final_price_diverge
    """
    ctx = _rich_completed(api)
    wo = ctx["wo"]
    # 12000 base + (3000+2500+2000) add-ons at full list = 19500, no discount/parts/surcharge.
    assert wo["quoted_price_cents"] == 19500, f"expected quote 19500, got {wo['quoted_price_cents']}"


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/pro_payout_provisional_vs_final_diverge
# ---------------------------------------------------------------------------
def test_provisional_payout_at_completion_excludes_redo_penalty(api):
    """PRD §3.7: "The `commission_cents` is the platform's cut: 25 percent of `gross_task_cents`
    (`PLATFORM_COMMISSION_BPS` is 2500 basis points), rounded half up to a whole cent."
    PRD §3.7: "The provisional `payout_cents` is then `gross_task_cents` minus `commission_cents`
    plus `parts_reimbursement_cents`."

    Design: Difficulty/dual_variant_calc/pro_payout_provisional_vs_final_diverge
    """
    ctx = setup_completed_order(api, base_price_cents=12000, commission_rate_bps=1000,
                                clock="2026-03-05T09:30:00Z")
    payout = ctx["payout"]
    # gross 12000, commission 25% = 3000, no parts -> provisional 9000.
    assert payout["status"] == PayoutStatus.PENDING.value
    assert payout["payout_cents"] == 9000, f"expected provisional 9000, got {payout['payout_cents']}"


def test_final_released_payout_subtracts_redo_penalty(api):
    """PRD §3.8: "the final payout is the provisional payout minus a per-redo penalty of 3000 cents
    (`REDO_PENALTY_CENTS`) times the order's `redo_count`, floored at 0 (never negative)."

    Design: Difficulty/dual_variant_calc/pro_payout_provisional_vs_final_diverge
    """
    ctx = setup_completed_order(api, base_price_cents=12000, commission_rate_bps=1000,
                                clock="2026-03-05T09:30:00Z")
    wo, pro, cust = ctx["wo"], ctx["pro"], ctx["customer"]
    redo_wo = request_redo(api, wo["id"], cust["id"])
    dispatch_order(api, wo["id"], redo_wo["version"])
    asg2 = offered_assignment_for(api, wo["id"])
    accept_assignment(api, asg2["id"], pro["id"])
    start_order(api, wo["id"], pro["id"])
    complete_order(api, wo["id"], pro["id"])
    set_clock(api, "2026-04-06T00:00:00Z")
    close_order(api, wo["id"])
    payout = payout_for(api, wo["id"])
    # provisional 9000 - 3000 * redo_count(1) = 6000.
    assert payout["status"] == PayoutStatus.RELEASED.value
    assert payout["payout_cents"] == 6000, f"expected final 6000, got {payout['payout_cents']}"


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/final_price_mincap_discount_and_maxflat_surcharge
# ---------------------------------------------------------------------------
def test_final_price_applies_capped_discount_and_flat_surcharge(api):
    """PRD §3.6: "the discount is 10 percent of the add-ons gross (`BUNDLE_DISCOUNT_BPS` is 1000
    basis points), rounded half up to a whole cent, but capped so it never exceeds 5000 cents
    (`MAX_BUNDLE_DISCOUNT_CENTS`) — the discount is the smaller of the rounded ten-percent figure
    and 5000 cents"
    PRD §3.6: "the surcharge is the greater of a flat 4000 cents (`AFTER_HOURS_FLAT_CENTS`) and 15
    percent of the install task's `base_price_cents` (`AFTER_HOURS_BPS` is 1500 basis points)
    rounded half up to a whole cent"

    Design: Difficulty/combinatorial_formula/final_price_mincap_discount_and_maxflat_surcharge
    """
    ctx = setup_completed_order(
        api, base_price_cents=12000, commission_rate_bps=1000,
        scheduled_start="2026-03-05T20:00:00Z", scheduled_end="2026-03-05T21:00:00Z",
        addon_prices=[20000, 20000, 20000], clock="2026-03-05T21:30:00Z")
    # addons 60000, discount min(6000, 5000)=5000 -> 55000; surcharge max(4000, 1800)=4000.
    # final = 12000 + 55000 + 0 parts + 4000 = 71000.
    assert ctx["wo"]["final_price_cents"] == 71000, f"got {ctx['wo']['final_price_cents']}"


def test_bundle_discount_not_applied_below_three_addons(api):
    """PRD §3.6: "a bundle discount is applied only when the order carries at least three add-ons
    (`BUNDLE_MIN_ADDONS` is 3): in that case the discount is 10 percent of the add-ons gross
    (`BUNDLE_DISCOUNT_BPS` is 1000 basis points), rounded half up to a whole cent, but capped so it
    never exceeds 5000 cents (`MAX_BUNDLE_DISCOUNT_CENTS`) — the discount is the smaller of the
    rounded ten-percent figure and 5000 cents; with fewer than three add-ons the discount is 0."

    Design: Difficulty/combinatorial_formula/final_price_mincap_discount_and_maxflat_surcharge
    """
    ctx = setup_completed_order(
        api, base_price_cents=12000, commission_rate_bps=1000,
        scheduled_start="2026-03-05T09:00:00Z", scheduled_end="2026-03-05T10:00:00Z",
        addon_prices=[20000, 20000], clock="2026-03-05T09:30:00Z")
    # 2 add-ons -> no discount; standard hours -> no surcharge; no parts.
    # final = 12000 + 40000 = 52000, equal to the quote (no divergent component present).
    assert ctx["wo"]["final_price_cents"] == 52000, f"got {ctx['wo']['final_price_cents']}"
    assert ctx["wo"]["final_price_cents"] == ctx["wo"]["quoted_price_cents"]


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/parts_billed_round_per_line_then_sum
# ---------------------------------------------------------------------------
def test_parts_billed_rounds_each_line_then_sums(api):
    """PRD §3.6: "the billed parts total is the sum of every part line's `line_billed_cents`,
    computed by rounding each line half up and then summing the rounded lines — the rounding is per
    line and then summed, never summed and then rounded, and the two can differ by a cent or more
    at fractional-cent lines."

    Design: Difficulty/combinatorial_formula/parts_billed_round_per_line_then_sum
    """
    parts = [{"name": "Anchor", "unit_cost_cents": 251, "quantity": 1, "markup_bps": 4000}] * 3
    ctx = setup_completed_order(
        api, base_price_cents=10000, commission_rate_bps=1000,
        scheduled_start="2026-03-05T09:00:00Z", scheduled_end="2026-03-05T10:00:00Z",
        parts=parts, clock="2026-03-05T09:30:00Z")
    for p in ctx["parts"]:
        assert p["line_billed_cents"] == 351, f"per-line 251*1.4=351.4->351, got {p['line_billed_cents']}"
    # 3 lines of 351 = 1053; sum-then-round would be round(3*351.4)=1054.
    assert ctx["wo"]["final_price_cents"] == 11053, f"got {ctx['wo']['final_price_cents']}"


def test_part_line_billed_uses_round_half_up(api):
    """PRD §3.6: "as the unit cost times quantity, marked up by the line's basis points, rounded
    half up to a whole cent: that is, `unit_cost_cents` multiplied by `quantity`, then multiplied
    by (10000 plus `markup_bps`) and divided by 10000, with the result rounded half up."

    Design: Difficulty/combinatorial_formula/parts_billed_round_per_line_then_sum
    """
    parts = [{"name": "Anchor", "unit_cost_cents": 333, "quantity": 1, "markup_bps": 5000}]
    ctx = setup_completed_order(
        api, base_price_cents=10000, commission_rate_bps=1000,
        scheduled_start="2026-03-05T09:00:00Z", scheduled_end="2026-03-05T10:00:00Z",
        parts=parts, clock="2026-03-05T09:30:00Z")
    # 333 * 1.5 = 499.5 -> round half up -> 500.
    assert ctx["parts"][0]["line_billed_cents"] == 500
    assert ctx["wo"]["final_price_cents"] == 10500, f"got {ctx['wo']['final_price_cents']}"


# ---------------------------------------------------------------------------
# Corner/calculations/quoted_price_computed_on_schedule_with_addons
# ---------------------------------------------------------------------------
def test_quoted_price_computed_on_schedule_with_addons(api):
    """PRD §3.3: "The `quoted_price_cents` is the install task's `base_price_cents` plus the sum of
    the `price_cents` of every add-on named in `selected_addon_ids`, at full list price — with no
    bundle discount, no parts, and no zone surcharge folded in."

    Design: Corner/calculations/quoted_price_computed_on_schedule_with_addons
    """
    ctx = setup_scheduled_order(api, base_price_cents=12000, addon_prices=[3000, 2500])
    wo = ctx["wo"]
    assert wo["status"] == WorkOrderStatus.SCHEDULED.value
    assert wo["quoted_price_cents"] == 17500, f"expected 17500, got {wo['quoted_price_cents']}"


# ---------------------------------------------------------------------------
# Corner/consistency_model/schedule_response_reflects_new_state_immediately
# ---------------------------------------------------------------------------
def test_schedule_response_reflects_new_state_immediately(api):
    """PRD §2.10: "the server performs all listed effects atomically, bumping the `version` and
    `updated_at` of every mutated resource that carries those fields, and recomputing every derived
    aggregate the effect names."
    PRD §3.3: "The `quoted_price_cents` is the install task's `base_price_cents` plus the sum of the
    `price_cents` of every add-on named in `selected_addon_ids`, at full list price — with no bundle
    discount, no parts, and no zone surcharge folded in."

    Design: Corner/consistency_model/schedule_response_reflects_new_state_immediately
    """
    ctx = setup_scheduled_order(api, base_price_cents=12000, addon_prices=[3000])
    wo = ctx["wo"]  # this dict is the schedule response body's data
    assert wo["status"] == WorkOrderStatus.SCHEDULED.value
    assert wo["quoted_price_cents"] == 15000, f"expected 15000, got {wo['quoted_price_cents']}"
