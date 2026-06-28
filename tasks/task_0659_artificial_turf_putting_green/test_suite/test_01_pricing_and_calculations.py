"""Pricing engine and derived-value calculations: quote totals, waste factors,
drainage tiers, base-prep costs, variant surcharges, warranty terms, callback
billing, and the dual-variant estimate/final and ledger calculations.

Each test translates exactly one design-index instance (queue A difficulty or
queue B corner) and cites the verbatim PRD rule it asserts.
"""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    api_client,
    TEST_USERS,
    make_customer_headers,
    fixtures as fx,
    factories as f,
)

ADMIN = TEST_USERS["ops_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]


# ─── Difficulty: dual_variant_calc ───────────────────────────────────────────
def test_quote_estimate_equals_frozen_final_on_send(api):
    """PRD §3.5: "Once a quote is `SENT` (and thereafter while `ACCEPTED`), its
    `total_cents` is a **final** figure frozen at send time from the then-current
    finalized scope and accepted design; later design edits do not change a sent
    quote's total."
    PRD §3.5: "and `material_subtotal_cents` is the sum of those two
    already-rounded lines."

    Design: Difficulty/dual_variant_calc/quote_estimate_vs_final_freeze_on_send
    """
    ctx = fx.setup_finalized_scope_project(variant="STANDARD")
    pid = ctx["project"]["id"]
    quote = fx.create_quote(pid, ctx["design"]["id"], ctx["scope"]["id"])
    # Estimate (DRAFT) total.
    assert quote["total_cents"] == 431568, f"estimate total {quote['total_cents']}"
    assert quote["material_subtotal_cents"] == 388800
    # Send freezes the figure as final.
    sent = validate_success(api_client.send_quote(pid, quote["id"], SALES))
    assert sent["status"] == "SENT"
    assert sent["total_cents"] == 431568, "final frozen total equals the estimate"


def test_quote_total_frozen_matches_pre_send_estimate(api):
    """PRD §3.5: "While a quote is still in `DRAFT` it is an **estimate**: it is
    computed from the design's net area as currently drafted and is recomputed if
    the design is edited before the quote is sent, so it is not frozen."

    Design: Difficulty/dual_variant_calc/quote_estimate_vs_final_freeze_on_send
    """
    ctx = fx.setup_finalized_scope_project(variant="STANDARD")
    pid = ctx["project"]["id"]
    quote = fx.create_quote(pid, ctx["design"]["id"], ctx["scope"]["id"])
    est = quote["total_cents"]
    sent = validate_success(api_client.send_quote(pid, quote["id"], SALES))
    # Re-read after send: the frozen final equals the DRAFT estimate.
    reread = validate_success(api_client.get_quote(pid, quote["id"], SALES))
    assert reread["total_cents"] == est == 431568


def test_ledger_settled_excludes_pending_balance(api):
    """PRD §3.7: "The signed outstanding figure is the contract total minus the
    deposit paid minus the balance paid plus the refunded amount; the
    `outstanding_balance_cents` exposed for display is that signed figure or zero,
    whichever is greater, while the signed value is what the ledger conserves."

    Design: Difficulty/dual_variant_calc/ledger_settled_vs_forward_projected_diverge
    """
    ctx = fx.setup_installed_project()
    pid = ctx["project"]["id"]
    cust_id = ctx["customer"]["id"]
    # Record a BALANCE payment but leave it PENDING (do not settle).
    fx.record_payment(pid, cust_id, "BALANCE", 302098)
    settled = validate_success(api_client.get_ledger(pid, ADMIN))
    assert settled["deposit_paid_cents"] == 129470
    assert settled["balance_paid_cents"] == 0, "pending balance is not settled"
    assert settled["outstanding_balance_cents"] == 302098


def test_ledger_forward_projected_includes_pending_balance(api):
    """PRD §3.7: "The ledger also offers a forward-projected view that
    additionally folds in `PENDING` payments as projected, producing a different
    outstanding figure from the settled-only view whenever pending payments exist;
    that projected view is requested by setting `include_pending` to true on the
    ledger read."

    Design: Difficulty/dual_variant_calc/ledger_settled_vs_forward_projected_diverge
    """
    ctx = fx.setup_installed_project()
    pid = ctx["project"]["id"]
    cust_id = ctx["customer"]["id"]
    fx.record_payment(pid, cust_id, "BALANCE", 302098)
    projected = validate_success(api_client.get_ledger(pid, ADMIN, params={"include_pending": True}))
    assert projected["outstanding_balance_cents"] == 0, "projected folds in the pending balance"


# ─── Difficulty: combinatorial_formula ───────────────────────────────────────
def test_material_subtotal_rounds_per_line_then_sums(api):
    """PRD §3.5: "The turf line is the priced design's net area multiplied by the
    turf's per-square-foot price, rounded half-up to whole cents; the infill line
    is the net area multiplied by the infill's per-square-foot price, rounded
    half-up to whole cents; and `material_subtotal_cents` is the sum of those two
    already-rounded lines."
    PRD §3.5: "Each line is rounded before the two are added — never the other way
    around."

    Design: Difficulty/combinatorial_formula/material_subtotal_round_per_line_then_sum
    """
    # gross 95.33, run 10 -> 1 run -> waste 5% -> net = 95.33 * 1.05 = 100.0965 -> 100.10
    ctx = fx.setup_finalized_scope_project(
        variant="STANDARD",
        measure_overrides={"gross_area_sqft": 95.33, "longest_run_ft": 10, "slope_pct": 1.0},
        turf_overrides={"price_per_sqft_cents": 3, "roll_width_ft": 15},
        infill_overrides={"price_per_sqft_cents": 3},
    )
    pid = ctx["project"]["id"]
    assert ctx["design"]["net_area_sqft"] == 100.10
    quote = fx.create_quote(pid, ctx["design"]["id"], ctx["scope"]["id"])
    # turf line = round(100.10*3)=round(300.30)=300; infill line=300; sum=600 (NOT round(600.60)=601)
    assert quote["material_subtotal_cents"] == 600, f"got {quote['material_subtotal_cents']}"


def test_quote_total_floored_at_minimum_job(api):
    """PRD §3.5: "The `total_cents` is that subtotal or the minimum-job floor of
    150000 cents, whichever is greater — no job is contracted below the floor."

    Design: Difficulty/combinatorial_formula/material_subtotal_round_per_line_then_sum
    """
    ctx = fx.setup_finalized_scope_project(
        variant="STANDARD",
        measure_overrides={"gross_area_sqft": 95.33, "longest_run_ft": 10, "slope_pct": 1.0},
        turf_overrides={"price_per_sqft_cents": 3, "roll_width_ft": 15},
        infill_overrides={"price_per_sqft_cents": 3},
    )
    pid = ctx["project"]["id"]
    quote = fx.create_quote(pid, ctx["design"]["id"], ctx["scope"]["id"])
    # subtotal = 600 + excavation(round(100.10*3*22)=6607) = 7207 -> floored to 150000.
    assert quote["total_cents"] == 150000


def test_drainage_tier_flat_poor_soil_resolves_to_panel(api):
    """PRD §3.4: "Otherwise, if the soil does not drain freely and the slope is
    below 2.0 percent, the tier is `DRAINAGE_PANEL` (a flat site with poor soil
    needs a panel)."

    Design: Difficulty/combinatorial_formula/drainage_tier_three_input_nonlinear
    """
    ctx = fx.setup_designed_project(
        variant="STANDARD",
        measure_overrides={"gross_area_sqft": 600, "longest_run_ft": 20, "slope_pct": 1.5, "soil_drains_freely": False},
    )
    pid = ctx["project"]["id"]
    scope = fx.create_base_prep_scope(pid, ctx["design"]["id"], base_depth_in=4)
    assert scope["drainage_tier"] == "DRAINAGE_PANEL"
    # net 648, panel 320/sqft -> 207360; excavation 648*4*22 = 57024.
    assert scope["drainage_cost_cents"] == 207360
    assert scope["excavation_cost_cents"] == 57024


def test_drainage_tier_steep_slope_resolves_to_french_drain(api):
    """PRD §3.4: "Otherwise, if the slope is at least 5.0 percent or the soil does
    not drain freely, the tier is `FRENCH_DRAIN`."

    Design: Difficulty/combinatorial_formula/drainage_tier_three_input_nonlinear
    """
    ctx = fx.setup_designed_project(
        variant="STANDARD",
        measure_overrides={"gross_area_sqft": 600, "longest_run_ft": 20, "slope_pct": 6.0, "soil_drains_freely": True},
    )
    pid = ctx["project"]["id"]
    scope = fx.create_base_prep_scope(pid, ctx["design"]["id"], base_depth_in=4)
    assert scope["drainage_tier"] == "FRENCH_DRAIN"
    # net 648, french 180/sqft -> 116640.
    assert scope["drainage_cost_cents"] == 116640


# ─── Difficulty: boundary_precision_check (slope 5.0) ────────────────────────
def test_drainage_slope_below_boundary_is_none(api):
    """PRD §3.4: "In every remaining case the tier is `NONE`."
    PRD §3.4: "if the slope is at least 5.0 percent or the soil does not drain
    freely, the tier is `FRENCH_DRAIN`."

    Design: Difficulty/boundary_precision_check/drainage_slope_boundary_5pct
    """
    ctx = fx.setup_designed_project(
        variant="STANDARD",
        measure_overrides={"gross_area_sqft": 600, "longest_run_ft": 20, "slope_pct": 4.99, "soil_drains_freely": True},
    )
    pid = ctx["project"]["id"]
    scope = fx.create_base_prep_scope(pid, ctx["design"]["id"], base_depth_in=4)
    assert scope["drainage_tier"] == "NONE", "slope 4.99 < 5.0 with free soil -> NONE"
    assert scope["drainage_cost_cents"] == 0


def test_drainage_slope_at_boundary_is_french_drain(api):
    """PRD §3.4: "Otherwise, if the slope is at least 5.0 percent or the soil does
    not drain freely, the tier is `FRENCH_DRAIN`."

    Design: Difficulty/boundary_precision_check/drainage_slope_boundary_5pct
    """
    ctx = fx.setup_designed_project(
        variant="STANDARD",
        measure_overrides={"gross_area_sqft": 600, "longest_run_ft": 20, "slope_pct": 5.0, "soil_drains_freely": True},
    )
    pid = ctx["project"]["id"]
    scope = fx.create_base_prep_scope(pid, ctx["design"]["id"], base_depth_in=4)
    assert scope["drainage_tier"] == "FRENCH_DRAIN", "slope exactly 5.0 -> FRENCH_DRAIN"
    assert scope["drainage_cost_cents"] == 116640  # 648 * 180


# ─── Corner: calculations ────────────────────────────────────────────────────
def test_net_area_computed_from_waste_factor(api):
    """PRD §3.2: "The `net_area_sqft` is the gross area minus the obstruction area,
    multiplied by one plus the waste factor expressed as a fraction (so a 12.0
    percent factor multiplies by 1.12), and the result is rounded half-up to two
    decimal places."
    PRD §3.2: "exactly two runs yields 8.0 percent"

    Design: Corner/entities/net_area_computed_input_value_ignored
    """
    # gross 600, run 20, roll_width 15 -> ceil(20/15)=2 runs -> 8.0% -> 600*1.08 = 648.00
    turf, infill = fx.setup_catalog()
    _cust, project, measure = fx.setup_measured_project()
    design = fx.create_design_layout(
        project["id"], measure["id"], turf["id"], infill["id"], "STANDARD"
    )
    assert design["waste_factor_pct"] == 8.0
    assert design["net_area_sqft"] == 648.0
    assert design["status"] == "DRAFT"


def test_waste_factor_three_run_tier(api):
    """PRD §3.2: "three or four runs yields 12.0 percent"
    PRD §3.2: "The `net_area_sqft` is the gross area minus the obstruction area,
    multiplied by one plus the waste factor expressed as a fraction (so a 12.0
    percent factor multiplies by 1.12), and the result is rounded half-up to two
    decimal places."

    Design: Corner/calculations/waste_factor_tier_boundaries
    """
    # gross 600, run 45, roll_width 15 -> ceil(45/15)=3 runs -> 12.0% -> 600*1.12 = 672.00
    turf, infill = fx.setup_catalog()
    _cust, project, measure = fx.setup_measured_project(
        measure_overrides={"gross_area_sqft": 600, "longest_run_ft": 45, "slope_pct": 1.0}
    )
    design = fx.create_design_layout(
        project["id"], measure["id"], turf["id"], infill["id"], "STANDARD"
    )
    assert design["waste_factor_pct"] == 12.0
    assert design["net_area_sqft"] == 672.0


def test_warranty_terms_plus_tier(api):
    """PRD §3.10: "a `PLUS` plan carries 36 months of coverage and one maintenance
    visit per year"
    PRD §3.10: "The plan is created in `PENDING` status with both `start_at` and
    `expires_at` unset, and the tier drives two computed terms."

    Design: Corner/calculations/warranty_terms_by_tier_plus
    """
    customer = fx.create_customer()
    project = fx.create_project(customer["id"])
    plan = fx.create_warranty_plan(project["id"], "PLUS")
    assert plan["coverage_months"] == 36
    assert plan["maintenance_visits_per_year"] == 1
    assert plan["status"] == "PENDING"


def test_variant_surcharge_pet_twelve_percent(api):
    """PRD §3.5: "Third, the `variant_surcharge_cents` is the material subtotal
    multiplied by the variant percentage from Section 3.3 (zero for `STANDARD`,
    12 percent for `PET`, 18 percent for `PLAYGROUND`, 25 percent for
    `PUTTING_GREEN`), rounded half-up."
    PRD §3.5: "The volume discount is keyed on the design's net area: a net area of
    at least 2000 square feet earns 10 percent, a net area of at least 1000 but
    below 2000 square feet earns 5 percent, and anything below 1000 square feet
    earns nothing"

    Design: Corner/calculations/variant_surcharge_pet_twelve_pct
    """
    # PET, gross 1000 run 30 roll 15 -> ceil(30/15)=2 runs -> 8% -> net 1080.
    # turf 600c, infill 150c: turf line 648000, infill 162000 -> material 810000.
    # surcharge = round(810000*0.12)=97200. base_prep depth 4: excavation round(1080*4*22)=95040,
    #   slope 3 free-draining STANDARD branch? variant=PET, soil drains, slope 3<5 -> NONE drainage.
    # pre = 810000 + 95040 + 97200 = 1002240. volume net 1080 >=1000 -> 5% -> round(1002240*0.05)=50112.
    # subtotal = 952128; total = max(952128,150000)=952128.
    ctx = fx.setup_finalized_scope_project(
        variant="PET",
        base_depth_in=4,
        measure_overrides={"gross_area_sqft": 1000, "longest_run_ft": 30, "slope_pct": 3.0},
        turf_overrides={"price_per_sqft_cents": 600, "pet_approved": True, "roll_width_ft": 15},
        infill_overrides={"price_per_sqft_cents": 150, "material": "ZEOLITE", "antimicrobial": True},
    )
    pid = ctx["project"]["id"]
    quote = fx.create_quote(pid, ctx["design"]["id"], ctx["scope"]["id"])
    assert quote["material_subtotal_cents"] == 810000
    assert quote["variant_surcharge_cents"] == 97200
    assert quote["total_cents"] == 952128


def test_drainage_tier_putting_green_always_panel(api):
    """PRD §3.4: "First, if the variant is `PUTTING_GREEN`, the `drainage_tier` is
    `DRAINAGE_PANEL` — putting greens are always panel-drained regardless of soil
    or slope."
    PRD §3.4: "a `DRAINAGE_PANEL` tier costs the net area multiplied by 320 cents
    per square foot rounded half-up."

    Design: Corner/calculations/drainage_tier_putting_green_always_panel
    """
    # gross 400, run 10, roll 15 -> 1 run -> 5% -> net 420. flat free-draining site.
    ctx = fx.setup_designed_project(
        variant="PUTTING_GREEN",
        measure_overrides={"gross_area_sqft": 400, "longest_run_ft": 10, "slope_pct": 1.0, "soil_drains_freely": True},
        turf_overrides={"price_per_sqft_cents": 700, "putting_rated": True, "pile_height_mm": 15, "roll_width_ft": 15},
        infill_overrides={"price_per_sqft_cents": 120, "coverage_lbs_per_sqft": 3},
    )
    pid = ctx["project"]["id"]
    scope = fx.create_base_prep_scope(pid, ctx["design"]["id"], base_depth_in=4)
    assert scope["drainage_tier"] == "DRAINAGE_PANEL"
    assert scope["drainage_cost_cents"] == 134400  # 420 * 320
    assert scope["excavation_cost_cents"] == 36960  # 420 * 4 * 22


def test_callback_billable_charge_out_of_warranty(api):
    """PRD §3.11: "A callback that is not covered is billable. When a callback is
    billable its `charge_cents` is a flat callback fee of 12500 cents plus a
    per-square-foot rework charge of 35 cents multiplied by the project's
    `billable_area_sqft`, rounded half-up to whole cents; when it is not billable
    the charge is zero."

    Design: Corner/calculations/callback_billable_charge_when_no_warranty
    """
    ctx = fx.setup_installed_project()  # STANDARD billable_area 648
    pid = ctx["project"]["id"]
    cust = make_customer_headers(ctx["customer"]["id"])
    cb = validate_success(
        api_client.create_callback(pid, f.create_callback_payload("WRINKLE"), cust),
        expected_status=201,
    )
    assert cb["billable"] is True, "no warranty referenced -> billable"
    assert cb["charge_cents"] == 35180  # 12500 + 648*35
