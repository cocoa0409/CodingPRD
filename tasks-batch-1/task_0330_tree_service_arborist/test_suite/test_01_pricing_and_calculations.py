"""Estimate pricing, surcharges, the dual pricing variants, and per-line
rounding order (PRD §3.4, §3.5, §3.10).

Difficulty: dual_variant_calc, combinatorial_formula (estimate rounding).
Corner: calculations section + emergency multiplier.
"""
from test_helpers import (
    validate_success,
    api_client,
    create_service_area,
    create_work_order,
    add_tree,
    assess,
    create_estimate,
    add_line_item,
    issue_estimate,
    TEST_USERS,
)


# ─── dual_variant_calc / estimate_total_per_job_vs_hourly_diverge ───


def _build_diverge_work_order(pricing_mode, is_emergency, area_id):
    """Area shared across both work orders; one heritage SEVERE near-utility
    tree (dbh=42, heritage, near-utility, lean=20, decay) + three lines
    REMOVAL/HAUL_OFF qty=3/STUMP qty=42 → subtotal 255900."""
    wo = create_work_order(
        area_id, pricing_mode=pricing_mode, is_emergency=is_emergency,
        site_address="1 Oak St",
    )
    tree = add_tree(
        wo["id"], species="Oak", dbh_inches=42, is_heritage=True,
        near_utility_line=True, lean_degrees=20, has_visible_decay=True,
    )
    assess(wo["id"])
    est = create_estimate(wo["id"])
    add_line_item(est["id"], service_type="REMOVAL", quantity=1, tree_asset_id=tree["id"])
    add_line_item(est["id"], service_type="HAUL_OFF", quantity=3)
    add_line_item(est["id"], service_type="STUMP_GRINDING", quantity=42, tree_asset_id=tree["id"])
    return wo, est


def test_per_job_estimate_applies_heritage_and_emergency(api):
    """PRD §3.5: "The `heritage_surcharge_cents` applies only under per-job
    pricing: when `pricing_mode` is `PER_JOB` and at least one `REMOVAL` line
    references a heritage tree, it is the service area's
    `heritage_surcharge_pct` applied to the integer subtotal and rounded
    half-up; in every other case, including all hourly estimates, it is zero."
    PRD §3.5: "The emergency multiplier is applied last and only when the work
    order's `is_emergency` is true: in that case the `total_cents` is the
    pre-emergency figure multiplied by 1.5 and rounded half-up, and
    `emergency_multiplier_applied` is recorded as true"

    Design: Difficulty/dual_variant_calc/estimate_total_per_job_vs_hourly_diverge
    """
    area = create_service_area(
        disposal_fee_cents_per_ton=8000, requires_permit_authority=True,
        heritage_surcharge_pct=0.15,
    )
    wo, est = _build_diverge_work_order("PER_JOB", True, area["id"])
    issued = issue_estimate(wo["id"], est["id"])
    assert issued["line_items_subtotal_cents"] == 255900
    assert issued["heritage_surcharge_cents"] == 38385
    assert issued["emergency_multiplier_applied"] is True
    assert issued["total_cents"] == 555698


def test_hourly_estimate_forces_heritage_zero_and_no_emergency(api):
    """PRD §3.5: "Under `HOURLY`, the heritage surcharge is forced to zero —
    the heritage premium is folded into metered hours rather than the quote"
    PRD §3.5: "These four amounts — subtotal plus the three surcharges — are
    added to form a pre-emergency figure."

    Design: Difficulty/dual_variant_calc/estimate_total_per_job_vs_hourly_diverge
    """
    area = create_service_area(
        disposal_fee_cents_per_ton=8000, requires_permit_authority=True,
        heritage_surcharge_pct=0.15,
    )
    wo, est = _build_diverge_work_order("HOURLY", False, area["id"])
    issued = issue_estimate(wo["id"], est["id"])
    assert issued["heritage_surcharge_cents"] == 0
    assert issued["emergency_multiplier_applied"] is False
    # subtotal 255900 + hazard SEVERE 0.20 -> 51180 + utility 25000 = 332080
    assert issued["total_cents"] == 332080


def test_per_job_and_hourly_totals_diverge_on_identical_lines(api):
    """PRD §3.5: "The two pricing modes diverge in what `total_cents` means
    downstream." PRD §3.5: "Under `HOURLY`, the heritage surcharge is forced
    to zero — the heritage premium is folded into metered hours rather than
    the quote"

    Design: Difficulty/dual_variant_calc/estimate_total_per_job_vs_hourly_diverge
    """
    area = create_service_area(
        disposal_fee_cents_per_ton=8000, requires_permit_authority=True,
        heritage_surcharge_pct=0.15,
    )
    wo_pj, est_pj = _build_diverge_work_order("PER_JOB", True, area["id"])
    wo_hr, est_hr = _build_diverge_work_order("HOURLY", False, area["id"])
    pj = issue_estimate(wo_pj["id"], est_pj["id"])
    hr = issue_estimate(wo_hr["id"], est_hr["id"])
    assert pj["total_cents"] != hr["total_cents"]
    assert pj["total_cents"] == 555698
    assert hr["total_cents"] == 332080


# ─── combinatorial_formula / estimate_round_per_line_then_sum_order ───


def test_estimate_rounds_per_line_before_summing(api):
    """PRD §3.4: "The line's `extended_cost_cents` is the unit cost multiplied
    by the quantity, rounded half-up to a whole number of cents — and crucially
    this rounding happens once per line, here, before any subtotaling."
    PRD §3.5: "the `line_items_subtotal_cents` is the sum of the
    already-rounded `extended_cost_cents` of every line — rounding happens per
    line first, then those integer cents are summed"

    Design: Difficulty/combinatorial_formula/estimate_round_per_line_then_sum_order
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000, heritage_surcharge_pct=0.15)
    # MODERATE hazard tree (dbh=20 + decay -> 50 MODERATE)
    wo = create_work_order(area["id"], pricing_mode="PER_JOB", site_address="4 Birch St")
    tree = add_tree(wo["id"], species="Maple", dbh_inches=20, has_visible_decay=True)
    assess(wo["id"])
    est = create_estimate(wo["id"])
    add_line_item(est["id"], service_type="HAUL_OFF", quantity=2.5)            # 8500*2.5 = 21250
    add_line_item(est["id"], service_type="STUMP_GRINDING", quantity=12.5,
                  tree_asset_id=tree["id"])                                     # 1200*12.5 = 15000
    issued = issue_estimate(wo["id"], est["id"])
    assert issued["line_items_subtotal_cents"] == 36250


def test_estimate_moderate_hazard_surcharge_rounded_individually(api):
    """PRD §3.5: "the `hazard_surcharge_cents` is computed from the work
    order's overall `hazard_level`: the surcharge percentage is twenty percent
    when the level is `SEVERE`, ten percent when it is `MODERATE`, and zero
    otherwise, and that percentage is applied to the integer subtotal and
    rounded half-up on its own."

    Design: Difficulty/combinatorial_formula/estimate_round_per_line_then_sum_order
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000, heritage_surcharge_pct=0.15)
    wo = create_work_order(area["id"], pricing_mode="PER_JOB", site_address="4 Birch St")
    tree = add_tree(wo["id"], species="Maple", dbh_inches=20, has_visible_decay=True)
    assess(wo["id"])
    est = create_estimate(wo["id"])
    add_line_item(est["id"], service_type="HAUL_OFF", quantity=2.5)
    add_line_item(est["id"], service_type="STUMP_GRINDING", quantity=12.5,
                  tree_asset_id=tree["id"])
    issued = issue_estimate(wo["id"], est["id"])
    assert issued["hazard_surcharge_cents"] == 3625    # round_half_up(36250 * 0.10)
    assert issued["heritage_surcharge_cents"] == 0
    assert issued["total_cents"] == 39875


# ─── Corner / calculations ──────────────────────────────


def test_removal_line_med_tier_unit_cost(api):
    """PRD §3.4: "A `REMOVAL` line is priced by the diameter tier of its
    referenced tree, billing the whole tree at the tier its `dbh_inches`
    falls in (the tier is not applied marginally): 180000 cents for a tree at
    least 36 inches, 95000 cents for a tree at least 18 but under 36 inches,
    and 45000 cents for a tree under 18 inches."

    Design: Corner/calculations/line_item_removal_tiered_unit_cost
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000)
    wo = create_work_order(area["id"], pricing_mode="PER_JOB")
    tree = add_tree(wo["id"], species="Oak", dbh_inches=25)
    assess(wo["id"])
    est = create_estimate(wo["id"])
    res = api.create_line_item(
        {"estimate_id": est["id"], "service_type": "REMOVAL", "quantity": 1,
         "tree_asset_id": tree["id"]},
        TEST_USERS["arborist_headers"],
    )
    li = validate_success(res, 201)
    assert li["unit_cost_cents"] == 95000
    assert li["extended_cost_cents"] == 95000


def test_utility_surcharge_applied_per_near_line_tree(api):
    """PRD §3.5: "The `utility_surcharge_cents` is a flat 25000 cents for each
    distinct tree that is `near_utility_line` and is referenced by a `REMOVAL`
    or `UTILITY_CLEARANCE` line on the estimate."

    Design: Corner/calculations/utility_surcharge_applied_per_near_line_tree
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000, heritage_surcharge_pct=0.15)
    wo = create_work_order(area["id"], pricing_mode="PER_JOB")
    tree = add_tree(wo["id"], species="Pine", dbh_inches=12, near_utility_line=True)
    assess(wo["id"])
    est = create_estimate(wo["id"])
    add_line_item(est["id"], service_type="REMOVAL", quantity=1, tree_asset_id=tree["id"])
    issued = issue_estimate(wo["id"], est["id"])
    assert issued["line_items_subtotal_cents"] == 45000
    assert issued["utility_surcharge_cents"] == 25000
    assert issued["hazard_surcharge_cents"] == 0
    assert issued["total_cents"] == 70000


def test_emergency_multiplier_flag_and_total(api):
    """PRD §3.5: "in that case the `total_cents` is the pre-emergency figure
    multiplied by 1.5 and rounded half-up, and `emergency_multiplier_applied`
    is recorded as true"

    Design: Corner/cross_cutting_complexity_layers/emergency_multiplier_threshold_flag
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000, heritage_surcharge_pct=0.15)
    wo = create_work_order(area["id"], pricing_mode="PER_JOB", is_emergency=True)
    tree = add_tree(wo["id"], species="Pine", dbh_inches=12)
    assess(wo["id"])
    est = create_estimate(wo["id"])
    add_line_item(est["id"], service_type="REMOVAL", quantity=1, tree_asset_id=tree["id"])
    issued = issue_estimate(wo["id"], est["id"])
    assert issued["line_items_subtotal_cents"] == 45000
    assert issued["emergency_multiplier_applied"] is True
    assert issued["total_cents"] == 67500    # round_half_up(45000 * 1.5)
