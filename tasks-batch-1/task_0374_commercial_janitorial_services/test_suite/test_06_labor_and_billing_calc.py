"""Dual-variant and combinatorial billing calculations (difficulty rules 1 & 2).

Translates SCAFFOLD_DIFFICULTY_DESIGN.yaml §1.8 dual_variant_calc and
combinatorial_formula instances. Each instance carries >=2 tests.
"""
from test_helpers import (
    validate_success, ApiErrorId, fixtures,
)
from test_helpers.test_users import TEST_USERS
from test_helpers.api_client import api_client

AM = TEST_USERS["account_manager_headers"]
FS = TEST_USERS["field_supervisor_headers"]


# ===========================================================================
# Rule 1 instance A: estimate_vs_actual_labor_minutes_on_same_visit
# ===========================================================================
def test_estimate_and_actual_labor_diverge_on_same_visit(api):
    """PRD §3.5: "Note that `estimated_labor_min` and `actual_labor_min` are
    distinct: the former is the forward projection from square footage or quoted
    hours computed at creation, while the latter is the chronological sum of
    clocked entries — the same visit, two different subjects".

    Design: Difficulty/dual_variant_calc/estimate_vs_actual_labor_minutes_on_same_visit
    """
    _, site, crew = fixtures.setup_account_site_crew(site_overrides={"cleanable_sqft": 10000})
    visit = fixtures.create_visit(
        site["id"], crew["id"], service_date="2026-06-16",
        planned_start_min=540, planned_end_min=600, visit_kind="ROUTINE")
    # estimate = ceil(10000/50) = 200 at creation
    assert visit["estimated_labor_min"] == 200
    fixtures.start_visit(visit["id"])
    fixtures.clock_full_entry(visit["id"], crew["id"], 480, 540)  # 60 min
    completed = validate_success(api.complete_visit(visit["id"], FS), 200)
    assert completed["actual_labor_min"] == 60
    assert completed["estimated_labor_min"] != completed["actual_labor_min"]


def test_estimate_unchanged_by_clock_after_completion(api):
    """PRD §3.3: "the system computes a forward labor estimate into
    `estimated_labor_min` before any clock data exists." PRD §3.5: "the system
    first recomputes the visit's `actual_labor_min`. It walks the visit's time
    entries whose `status` is `COMPLETED` ... and accumulates each entry's
    `clocked_min` into a running sum that becomes `actual_labor_min`".

    Design: Difficulty/dual_variant_calc/estimate_vs_actual_labor_minutes_on_same_visit
    """
    _, site, crew = fixtures.setup_account_site_crew(site_overrides={"cleanable_sqft": 10000})
    visit = fixtures.create_started_visit(
        site["id"], crew["id"], service_date="2026-06-16",
        planned_start_min=540, planned_end_min=600, visit_kind="ROUTINE")
    fixtures.clock_full_entry(visit["id"], crew["id"], 480, 540)
    completed = validate_success(api.complete_visit(visit["id"], FS), 200)
    # estimate stays the forward projection (200), actual is the clocked sum (60)
    assert completed["estimated_labor_min"] == 200
    assert completed["actual_labor_min"] == 60


# ===========================================================================
# Rule 1 instance B: provisional_vs_final_period_total_on_billing_period
# ===========================================================================
def test_period_total_provisional_then_final_holdback(api):
    """PRD §3.9: "in the **provisional** variant, used while the period is `OPEN`,
    `holdback_cents` is forced to 0 because quality is not yet final; in the
    **final** variant, used when the period closes, `holdback_cents` is
    `base_cents` multiplied by the contract's `quality_holdback_pct` rounded
    half-up to whole cents when `mean_quality_score` is non-null and strictly
    below the site's `quality_target`, and 0 otherwise."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_period_total_on_billing_period
    """
    bundle = fixtures.setup_billing_scenario(
        site_overrides={"cleanable_sqft": 10000, "quality_target": 85},
        contract_overrides={"monthly_base_cents": 300000, "hourly_rate_cents": 6000,
                            "quality_holdback_pct": 0.05})
    site, crew, period, acct = bundle["site"], bundle["crew"], bundle["period"], bundle["account"]
    # provisional while OPEN: base 300000, holdback 0
    assert period["total_cents"] == 300000
    assert period["holdback_cents"] == 0
    visit = fixtures.create_completed_routine_visit(
        site["id"], crew["id"], service_date="2026-06-10",
        planned_start_min=540, planned_end_min=600)
    validate_success(api.create_inspection({"visit_id": visit["id"], "score": 50}, FS), 201)
    closed = fixtures.close_period(period["id"], acct["id"])
    # final: holdback = round(300000 * 0.05) = 15000; total = 300000 - 15000
    assert closed["holdback_cents"] == 15000
    assert closed["total_cents"] == 285000


def test_period_provisional_total_zero_holdback_before_close(api):
    """PRD §3.9: "While the period is `OPEN`, this total is provisional and rises
    or falls as visits complete and credits post; at close it is finalized and
    frozen into the ledger." PRD §3.9: "in the **provisional** variant, used while
    the period is `OPEN`, `holdback_cents` is forced to 0 because quality is not
    yet final".

    Design: Difficulty/dual_variant_calc/provisional_vs_final_period_total_on_billing_period
    """
    bundle = fixtures.setup_billing_scenario(
        site_overrides={"cleanable_sqft": 10000, "quality_target": 85},
        contract_overrides={"monthly_base_cents": 300000, "hourly_rate_cents": 6000,
                            "quality_holdback_pct": 0.05})
    site, crew, period = bundle["site"], bundle["crew"], bundle["period"]
    visit = fixtures.create_completed_routine_visit(
        site["id"], crew["id"], service_date="2026-06-10",
        planned_start_min=540, planned_end_min=600)
    validate_success(api.create_inspection({"visit_id": visit["id"], "score": 50}, FS), 201)
    # still OPEN: holdback forced 0, total still 300000 (no periodic, no credit)
    fetched = validate_success(api.get_billing_period(period["id"], AM), 200)
    assert fetched["status"] == "OPEN"
    assert fetched["holdback_cents"] == 0
    assert fetched["total_cents"] == 300000


# ===========================================================================
# Rule 2 instance A: periodic_charge_tiered_overage_mode_a
# ===========================================================================
def test_periodic_charge_overage_tier_at_1_5x(api):
    """PRD §3.6: "the overage portion is the overage minutes multiplied by the
    per-minute rate multiplied by an overage multiplier of 1.5, rounded half-up to
    whole cents; and the periodic charge is the straight portion plus the overage
    portion — each component rounded first, then summed in that pinned order".

    Design: Difficulty/combinatorial_formula/periodic_charge_tiered_overage_mode_a
    """
    bundle = fixtures.setup_billing_scenario(
        site_overrides={"floor_type": "VCT"},
        contract_overrides={"monthly_base_cents": 300000, "hourly_rate_cents": 6000})
    # quoted 2h=120min, clocked 200min -> overage 80min
    _job, visit = fixtures.setup_completed_periodic_visit(
        bundle["site"]["id"], bundle["crew"]["id"], 480, 680,
        job_overrides={"quoted_hours": 2},
        dispatch_overrides={"planned_start_min": 480, "planned_end_min": 720})
    assert visit["actual_labor_min"] == 200
    period = validate_success(api.get_billing_period(bundle["period"]["id"], AM), 200)
    # straight 120*100=12000, overage 80*100*1.5=12000, sum 24000
    assert period["periodic_cents"] == 24000


def test_periodic_charge_billed_on_greater_of_quote_and_actual(api):
    """PRD §3.6: "The add-on is billed on the greater of the quoted and actual
    labor, with an overage surcharge on the minutes beyond the quote." PRD §3.6:
    "the billable minutes are the larger of the two; the overage minutes are the
    actual minutes minus the quoted minutes, but never less than 0".

    Design: Difficulty/combinatorial_formula/periodic_charge_tiered_overage_mode_a
    """
    bundle = fixtures.setup_billing_scenario(
        site_overrides={"floor_type": "VCT"},
        contract_overrides={"monthly_base_cents": 300000, "hourly_rate_cents": 6000})
    _job, visit = fixtures.setup_completed_periodic_visit(
        bundle["site"]["id"], bundle["crew"]["id"], 480, 680,
        job_overrides={"quoted_hours": 2},
        dispatch_overrides={"planned_start_min": 480, "planned_end_min": 720})
    assert visit["actual_labor_min"] == 200  # > quoted 120
    period = validate_success(api.get_billing_period(bundle["period"]["id"], AM), 200)
    assert period["periodic_cents"] == 24000


# ===========================================================================
# Rule 2 instance B: period_total_pinned_holdback_eval_order_mode_c
# ===========================================================================
def _setup_periodic_and_routine_deficient_period():
    """Active period with: a captured PERIODIC charge of 24000 and a deficient
    routine inspection. Returns (bundle, period_id)."""
    bundle = fixtures.setup_billing_scenario(
        site_overrides={"floor_type": "VCT", "cleanable_sqft": 8000, "quality_target": 85},
        contract_overrides={"monthly_base_cents": 300000, "hourly_rate_cents": 6000,
                            "callback_credit_pct": 0.10, "quality_holdback_pct": 0.05})
    site, crew = bundle["site"], bundle["crew"]
    # PERIODIC: quoted 2h, actual 200 -> periodic 24000
    fixtures.setup_completed_periodic_visit(
        site["id"], crew["id"], 480, 680,
        job_overrides={"quoted_hours": 2},
        dispatch_overrides={"planned_start_min": 480, "planned_end_min": 720})
    # ROUTINE deficient: separate service_date / window to avoid double-book
    rvisit = fixtures.create_completed_routine_visit(
        site["id"], crew["id"], service_date="2026-06-14",
        planned_start_min=60, planned_end_min=120, clock_in_min=60, clock_out_min=120)
    validate_success(api_client.create_inspection({"visit_id": rvisit["id"], "score": 70}, FS), 201)
    return bundle


def test_period_holdback_keyed_off_base_not_total(api):
    """PRD §3.9: "Because the holdback is keyed off `base_cents` rather than off
    the running total, the order breaks the apparent cycle." PRD §3.9: "in the
    **final** variant, used when the period closes, `holdback_cents` is
    `base_cents` multiplied by the contract's `quality_holdback_pct` rounded
    half-up to whole cents when `mean_quality_score` is non-null and strictly
    below the site's `quality_target`".

    Design: Difficulty/combinatorial_formula/period_total_pinned_holdback_eval_order_mode_c
    """
    bundle = _setup_periodic_and_routine_deficient_period()
    closed = fixtures.close_period(bundle["period"]["id"], bundle["account"]["id"])
    # holdback = round(300000 * 0.05) = 15000, computed from base, not from total
    assert closed["holdback_cents"] == 15000


def test_period_total_pinned_order_base_plus_periodic_minus_holdback(api):
    """PRD §3.9: "Finally, `total_cents` is `base_cents` plus `periodic_cents`
    minus `callback_credit_cents` minus `holdback_cents`."

    Design: Difficulty/combinatorial_formula/period_total_pinned_holdback_eval_order_mode_c
    """
    bundle = _setup_periodic_and_routine_deficient_period()
    closed = fixtures.close_period(bundle["period"]["id"], bundle["account"]["id"])
    # 300000 + 24000 - 0 - 15000 = 309000
    assert closed["periodic_cents"] == 24000
    assert closed["holdback_cents"] == 15000
    assert closed["total_cents"] == 309000
