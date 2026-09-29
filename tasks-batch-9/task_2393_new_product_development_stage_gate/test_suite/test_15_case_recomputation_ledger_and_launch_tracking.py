"""Weighted pricing, whole-set case recomputation, the live-commitment ledger,
the renormalised launch-readiness denominator and the post-launch decision floors."""
import pytest

from test_helpers import (
    add_forecast_line,
    add_timepoint,
    assert_attainment_decision,
    assert_business_case,
    assert_committed_budget_equals_live_sum,
    assert_deliverable,
    assert_post_launch_period,
    assert_project,
    book_pilot_run,
    cancel_pilot_run,
    complete_pilot_run,
    create_formulation,
    decide_deliverable,
    deliverable_payload,
    intake_project,
    open_business_case,
    open_shelf_life_study,
    post_launch_period_payload,
    read_project,
    register_pilot_line,
    register_stage_gate,
    set_clock,
    setup_launched_project,
    start_pilot_run,
    submit_deliverable,
    validate_success,
)

SNACK_PROJECT = {
    "name": "Toffee Crunch Bites",
    "brand": "GrainWell",
    "category": "SNACK",
    "project_type": "LINE_EXTENSION",
    "strategic_fit_score": 8,
    "consumer_need_score": 7,
    "target_gross_margin_pct": 36,
    "category_attractiveness_score": 7,
    "development_budget_cap_usd": 500000.00,
}
WEIGHTED_CASE = {
    "variant_mode": "TOP_DOWN",
    "category_size_units_year": 1000000,
    "target_share_pct": 20.00,
    "cogs_per_unit_usd": 2.0000,
    "slotting_fees_usd": 0.00,
    "capex_usd": 200000.00,
    "discount_rate_pct": 10.00,
}
CHEAP_WIDE_LINE = {
    "channel": "GROCERY",
    "store_count": 3000,
    "base_velocity_units_per_store_week": 1.00,
    "promo_weeks": 0,
    "promo_lift_pct": 0.00,
    "list_price_usd": 4.0000,
}
DEAR_NARROW_LINE = {
    "channel": "MASS",
    "store_count": 1000,
    "base_velocity_units_per_store_week": 1.00,
    "promo_weeks": 0,
    "promo_lift_pct": 0.00,
    "list_price_usd": 8.0000,
}
RECOMPUTE_CASE = {
    "variant_mode": "BOTTOM_UP",
    "category_size_units_year": 5000000,
    "target_share_pct": 3.00,
    "cogs_per_unit_usd": 3.2000,
    "slotting_fees_usd": 50000.00,
    "capex_usd": 300000.00,
    "discount_rate_pct": 9.00,
}
RECOMPUTE_FIRST_LINE = {
    "channel": "GROCERY",
    "store_count": 2400,
    "base_velocity_units_per_store_week": 1.20,
    "promo_weeks": 4,
    "promo_lift_pct": 30.00,
    "list_price_usd": 5.7500,
}
RECOMPUTE_SECOND_LINE = {
    "channel": "MASS",
    "store_count": 1200,
    "base_velocity_units_per_store_week": 1.50,
    "promo_weeks": 0,
    "promo_lift_pct": 0.00,
    "list_price_usd": 3.0000,
}
COMMERCIAL_GATE_3 = {
    "gate_number": 3,
    "stage_from": "PILOT_QUALIFIED",
    "stage_to": "LAUNCH_READY",
    "quorum_size": 1,
    "veto_functions": [],
    "npv_hurdle_usd": 0.00,
    "payback_months_max": 24,
    "gross_margin_floor_pct": 0.00,
    "readiness_floor_index": 0.00,
}
# 4000000 * 4.00% = 160000 annual units, so plan_units_per_period lands on 40000.00.
PLAN_OF_FORTY_THOUSAND_CASE = {
    "variant_mode": "TOP_DOWN",
    "category_size_units_year": 4000000,
    "target_share_pct": 4.00,
    "cogs_per_unit_usd": 2.5000,
    "slotting_fees_usd": 0.00,
    "capex_usd": 100000.00,
    "discount_rate_pct": 10.00,
}
PLAN_OF_FORTY_THOUSAND_LINE = {
    "channel": "GROCERY",
    "store_count": 2000,
    "base_velocity_units_per_store_week": 1.00,
    "promo_weeks": 0,
    "promo_lift_pct": 0.00,
    "list_price_usd": 5.0000,
}


def _case_probe_project(name="Toffee Crunch Bites", **overrides):
    return intake_project(owner_user_id="lead-case", **dict(SNACK_PROJECT, name=name, **overrides))


def _add_checklist_item(api, project_id, gate_id, deliverable_type, owner_function, headers):
    return validate_success(
        api.create_deliverable(
            project_id,
            deliverable_payload(
                gate_id, deliverable_type=deliverable_type, owner_function=owner_function
            ),
            headers,
        ),
        201,
    )


def test_avg_list_price_weights_each_channel_price_by_its_store_count(
    api, innovation_lead_headers
):
    """A 3000-store line at 4.0000 and a 1000-store line at 8.0000 average to 5.0000.

    PRD: "Independently, `avg_list_price_usd` is the store-count-weighted mean list price —
    the sum over lines of `list_price_usd` multiplied by `store_count`, divided by the sum of
    `store_count` across lines, rounded half up to four decimal places."

    Design: Corner/calculations/calc_avg_list_price_is_store_count_weighted
    """
    set_clock("2026-08-03T00:00:00Z")
    project = _case_probe_project()
    case = open_business_case(project["id"], **WEIGHTED_CASE)

    add_forecast_line(case["id"], **CHEAP_WIDE_LINE)
    add_forecast_line(case["id"], **DEAR_NARROW_LINE)
    stored = validate_success(api.get_business_case(case["id"], innovation_lead_headers))

    assert_business_case(stored)
    assert stored["avg_list_price_usd"] == pytest.approx(5.0000, abs=0.00005), (
        "(4.0000 * 3000 + 8.0000 * 1000) / 4000 = 5.0000"
    )
    assert stored["avg_list_price_usd"] != pytest.approx(6.0000, abs=0.00005), (
        "6.0000 is the unweighted mean of the two prices"
    )
    assert stored["annual_units"] == 200000, "1000000 * 20.00% = 200000"
    assert stored["gross_revenue_usd"] == pytest.approx(1000000.00, abs=0.01), (
        "200000 units at the weighted 5.0000 price"
    )


def test_weighted_price_lands_gross_revenue_on_the_inclusive_trade_tier_edge(
    api, innovation_lead_headers
):
    """Gross revenue of exactly 1000000.00 pays the 12.00 tier and carries the whole chain.

    PRD: "1. `trade_spend_rate_pct` is selected from a tiered table keyed on **gross**
    revenue, not net: `10.00` when `gross_revenue_usd` is below `1000000.00`, `12.00` when it
    is at least `1000000.00` and below `5000000.00`, and `15.00` when it is at least
    `5000000.00`."

    Design: Corner/calculations/calc_avg_list_price_is_store_count_weighted
    """
    set_clock("2026-08-03T00:00:00Z")
    project = _case_probe_project(name="Toffee Crunch Bites Tier Edge")
    case = open_business_case(project["id"], **WEIGHTED_CASE)

    add_forecast_line(case["id"], **CHEAP_WIDE_LINE)
    add_forecast_line(case["id"], **DEAR_NARROW_LINE)
    stored = validate_success(api.get_business_case(case["id"], innovation_lead_headers))

    assert stored["gross_revenue_usd"] == pytest.approx(1000000.00, abs=0.01)
    assert stored["trade_spend_rate_pct"] == pytest.approx(12.00, abs=0.01), (
        "the lower bound of the middle tier is inclusive"
    )
    assert stored["trade_spend_rate_pct"] != pytest.approx(10.00, abs=0.001)
    assert stored["trade_spend_usd"] == pytest.approx(120000.00, abs=0.01)
    assert stored["net_revenue_usd"] == pytest.approx(880000.00, abs=0.01)
    assert stored["gross_margin_pct"] == pytest.approx(54.55, abs=0.01)
    assert stored["npv_usd"] == pytest.approx(1140465.82, abs=0.01)
    assert stored["payback_months"] == 5


def test_zero_net_revenue_yields_a_zero_margin_percentage_by_definition(
    api, innovation_lead_headers
):
    """Slotting fees consume the post-trade revenue, so the margin percentage guards to 0.00.

    PRD: "6. `gross_margin_pct` is `gross_margin_usd` divided by `net_revenue_usd`, multiplied
    by 100 — and it is `0.00` by definition when `net_revenue_usd` is zero. It may be negative
    when costs exceed net revenue."

    Design: Corner/calculations/calc_zero_net_revenue_guard_returns_zero_margin_pct
    """
    set_clock("2026-08-03T00:00:00Z")
    project = _case_probe_project(name="Toffee Crunch Minis")
    case = open_business_case(
        project["id"], variant_mode="TOP_DOWN", category_size_units_year=2000000,
        target_share_pct=5.00, cogs_per_unit_usd=1.0000, slotting_fees_usd=180000.00,
        capex_usd=0.00, discount_rate_pct=10.00,
    )

    line_response = api.create_forecast_line(
        case["id"],
        {
            "channel": "GROCERY", "store_count": 2000,
            "base_velocity_units_per_store_week": 1.00, "promo_weeks": 0,
            "promo_lift_pct": 0.00, "list_price_usd": 2.0000,
        },
        innovation_lead_headers,
    )
    validate_success(line_response, 201)
    stored = validate_success(api.get_business_case(case["id"], innovation_lead_headers))

    assert stored["gross_revenue_usd"] == pytest.approx(200000.00, abs=0.01)
    assert stored["trade_spend_rate_pct"] == pytest.approx(10.00, abs=0.01)
    assert stored["trade_spend_usd"] == pytest.approx(20000.00, abs=0.01)
    assert stored["net_revenue_usd"] == pytest.approx(0.00, abs=0.01), (
        "200000.00 less 20000.00 of trade less 180000.00 of slotting is exactly zero"
    )
    assert stored["gross_margin_usd"] == pytest.approx(-100000.00, abs=0.01), (
        "nothing clamps the margin at zero"
    )
    assert stored["gross_margin_pct"] == pytest.approx(0.00, abs=0.01), (
        "0.00 here is the zero-denominator guard, not break-even"
    )
    assert stored["npv_usd"] == pytest.approx(-279263.71, abs=0.01)
    assert stored["payback_months"] == 999, "the never sentinel"
    assert stored["status"] == "COMPUTED", (
        "a value-destroying case is stored rather than refused"
    )


def test_case_is_re_derived_from_the_full_line_set_on_each_write(api, innovation_lead_headers):
    """A second line re-derives every field rather than topping up the first line's totals.

    PRD: "The first line moves the case `DRAFT → COMPUTED`; each subsequent line leaves it in
    `COMPUTED` (a `COMPUTED → COMPUTED` self-loop) and recomputes every financial field from
    the **full** line set rather than adjusting incrementally."

    Design: Corner/calculations/calc_case_recomputed_from_the_full_line_set_on_each_write
    """
    set_clock("2026-08-03T00:00:00Z")
    project = _case_probe_project(name="Toffee Crunch Bites Recompute")
    case = open_business_case(project["id"], **RECOMPUTE_CASE)

    add_forecast_line(case["id"], **RECOMPUTE_FIRST_LINE)
    after_one = validate_success(api.get_business_case(case["id"], innovation_lead_headers))
    add_forecast_line(case["id"], **RECOMPUTE_SECOND_LINE)
    after_two = validate_success(api.get_business_case(case["id"], innovation_lead_headers))

    assert after_one["annual_units"] == 153216
    assert after_one["gross_revenue_usd"] == pytest.approx(880992.00, abs=0.01)
    assert after_one["trade_spend_rate_pct"] == pytest.approx(10.00, abs=0.01)
    assert after_one["npv_usd"] == pytest.approx(418503.80, abs=0.01)
    assert after_one["payback_months"] == 14
    assert after_two["annual_units"] == 246816, "153216 + 93600 line units"
    assert after_two["gross_revenue_usd"] == pytest.approx(1161792.00, abs=0.01)
    assert after_two["avg_list_price_usd"] == pytest.approx(4.8333, abs=0.00005), (
        "the weighted mean price falls once the cheaper channel joins"
    )
    assert after_two["npv_usd"] == pytest.approx(219292.79, abs=0.01)
    assert after_two["npv_usd"] < after_one["npv_usd"], (
        "adding a profitable second line lowered the NPV, which only a full re-derivation "
        "can produce"
    )
    assert after_one["case_type"] == "PRELIMINARY"
    assert after_two["case_type"] == "PRELIMINARY"
    assert after_two["status"] == "COMPUTED"


def test_second_line_re_keys_the_trade_tier_rather_than_reusing_it(api, innovation_lead_headers):
    """The tier re-keys 10.00 to 12.00 on the new gross, so trade spend is 139415.04.

    PRD: "1. `trade_spend_rate_pct` is selected from a tiered table keyed on **gross**
    revenue, not net: `10.00` when `gross_revenue_usd` is below `1000000.00`, `12.00` when it
    is at least `1000000.00` and below `5000000.00`, and `15.00` when it is at least
    `5000000.00`."

    Design: Corner/calculations/calc_case_recomputed_from_the_full_line_set_on_each_write
    """
    set_clock("2026-08-03T00:00:00Z")
    project = _case_probe_project(name="Toffee Crunch Bites Re-key")
    case = open_business_case(project["id"], **RECOMPUTE_CASE)

    add_forecast_line(case["id"], **RECOMPUTE_FIRST_LINE)
    add_forecast_line(case["id"], **RECOMPUTE_SECOND_LINE)
    stored = validate_success(api.get_business_case(case["id"], innovation_lead_headers))

    assert stored["trade_spend_rate_pct"] == pytest.approx(12.00, abs=0.01), (
        "1161792.00 of gross revenue sits in the middle tier"
    )
    assert stored["trade_spend_usd"] == pytest.approx(139415.04, abs=0.01)
    assert stored["trade_spend_usd"] != pytest.approx(116179.20, abs=0.01), (
        "116179.20 is what a retained 10.00 rate would have charged"
    )
    assert stored["net_revenue_usd"] == pytest.approx(972376.96, abs=0.01)
    assert stored["gross_margin_pct"] == pytest.approx(18.78, abs=0.01)
    assert stored["payback_months"] == 19


def test_committed_ledger_counts_only_live_runs_and_studies(api, rnd_lead_headers):
    """A completed run and a failed study hold their money; a cancelled run released it.

    PRD: "`development_budget_committed_usd` on a project is, at every observable instant,
    exactly the sum of `committed_cost_usd` across that project's live pilot runs — those
    whose `status` is `SCHEDULED`, `RUNNING` or `COMPLETED` — plus `committed_cost_usd` across
    its live stability studies — those whose `status` is `ACTIVE`, `PASSED` or `FAILED` —
    rounded half up to two decimal places."

    Design: Corner/calculations/calc_committed_ledger_counts_only_live_commitments
    """
    set_clock("2026-08-03T00:00:00Z")
    pilot_line = register_pilot_line(
        plant_name="Toledo", line_code="TOL-11", allergen_regime="NONE"
    )
    project = _case_probe_project(name="Toffee Crunch Bites Ledger")
    formulation = create_formulation(
        project["id"], spec_summary="Toffee inclusion at 12 percent",
        allergen_regime="NONE", target_shelf_life_days=180, unit_cost_usd=3.2000,
    )

    completed = book_pilot_run(
        formulation["id"], pilot_line["id"],
        window_start="2026-08-01T08:00:00Z", window_end="2026-08-01T16:00:00Z",
        planned_units=10000, committed_cost_usd=10000.00,
    )
    start_pilot_run(completed["id"])
    completed = complete_pilot_run(completed["id"], 10000)
    cancelled = book_pilot_run(
        formulation["id"], pilot_line["id"],
        window_start="2026-08-04T08:00:00Z", window_end="2026-08-04T16:00:00Z",
        planned_units=12000, committed_cost_usd=50000.00,
    )
    cancelled = cancel_pilot_run(cancelled["id"], "Co-packer pulled the slot.")
    study = open_shelf_life_study(
        formulation["id"], duration_days=180, committed_cost_usd=20000.00,
        start_at="2026-08-05T00:00:00Z",
    )
    study = add_timepoint(study["id"], 10, 55.00)
    stored_project = read_project(project["id"])
    stored_formulation = validate_success(
        api.get_formulation(formulation["id"], rnd_lead_headers)
    )

    assert_project(stored_project)
    assert completed["status"] == "COMPLETED"
    assert cancelled["status"] == "CANCELLED"
    assert study["status"] == "FAILED"
    assert study["verdict"] == "FAIL"
    assert study["min_quality_score"] == pytest.approx(55.00, abs=0.01), (
        "the sub-60.00 reading closed the study without waiting for day 180"
    )
    assert stored_formulation["status"] == "PILOT_PASSED", "the failed study left it alone"
    assert_committed_budget_equals_live_sum(stored_project, [10000.00, 20000.00])
    assert stored_project["development_budget_committed_usd"] == pytest.approx(
        30000.00, abs=0.01
    )
    assert stored_project["development_budget_committed_usd"] != pytest.approx(
        80000.00, abs=0.01
    ), "80000.00 is the sum of every commitment ever created on the formulation"
    assert stored_project["development_budget_committed_usd"] != pytest.approx(
        10000.00, abs=0.01
    ), "the FAILED study still holds its 20000.00"


def test_launch_readiness_denominator_spans_only_the_required_readiness_types(
    api, gate_chair_headers
):
    """A gate demanding two readiness types plus a non-readiness type divides by 0.55.

    PRD: "The required set is the intersection of those four types with the
    `required_deliverable_types` of the stage gate whose `stage_to` is `LAUNCH_READY`. The
    denominator is the sum of the weights over that required set; the numerator is the sum of
    the weights over those required types whose checklist item is `APPROVED`, and a `WAIVED`
    item contributes nothing to the numerator even though it satisfies gate completeness."

    Design: Corner/calculations/calc_launch_readiness_denominator_covers_only_readiness_types
    """
    set_clock("2026-08-03T00:00:00Z")
    gate3 = register_stage_gate(
        category="SNACK",
        required_deliverable_types=[
            "MANUFACTURING_READINESS", "SALES_SELL_IN_PLAN", "SHELF_LIFE_REPORT",
        ],
        **COMMERCIAL_GATE_3,
    )
    project = _case_probe_project(name="Toffee Crunch Bites Denominator")

    manufacturing = _add_checklist_item(
        api, project["id"], gate3["id"], "MANUFACTURING_READINESS", "OPERATIONS",
        gate_chair_headers,
    )
    _add_checklist_item(
        api, project["id"], gate3["id"], "SALES_SELL_IN_PLAN", "SALES", gate_chair_headers
    )
    _add_checklist_item(
        api, project["id"], gate3["id"], "SHELF_LIFE_REPORT", "QUALITY", gate_chair_headers
    )
    submit_deliverable(
        manufacturing["id"], evidence_url="https://npd.example/dn/mfg-readiness",
        submitter_user_id="sub-dn",
    )
    approved = decide_deliverable(manufacturing["id"], "APPROVE", decider_user_id="rev-dn")
    readiness = validate_success(api.get_launch_readiness(project["id"], gate_chair_headers))
    stored_project = read_project(project["id"])

    assert_deliverable(approved)
    assert approved["status"] == "APPROVED"
    assert readiness["launch_readiness_pct"] == pytest.approx(63.64, abs=0.01), (
        "0.35 over the 0.55 denominator of manufacturing plus sales"
    )
    assert readiness["launch_readiness_pct"] != pytest.approx(35.00, abs=0.001), (
        "35.00 is what a full four-type denominator of 1.00 would give"
    )
    assert readiness["launch_readiness_pct"] != pytest.approx(33.33, abs=0.001), (
        "33.33 is what an equal-weight three-item checklist would give"
    )
    assert readiness["blocking_deliverable_types"] == ["SALES_SELL_IN_PLAN"], (
        "the still-pending SHELF_LIFE_REPORT is not a readiness type"
    )
    assert stored_project["launch_readiness_pct"] == pytest.approx(63.64, abs=0.01)


def test_launch_readiness_is_zero_when_the_gate_demands_no_readiness_type(
    api, gate_chair_headers
):
    """A commercialisation gate demanding only a stability report reads 0.00 with HTTP 200.

    PRD: "`launch_readiness_pct` is `0.00` when the denominator is zero, and otherwise the
    numerator divided by the denominator, multiplied by 100, rounded half up to two decimal
    places."

    Design: Corner/calculations/calc_launch_readiness_denominator_covers_only_readiness_types
    """
    set_clock("2026-08-03T00:00:00Z")
    gate3 = register_stage_gate(
        category="BEVERAGE",
        required_deliverable_types=["SHELF_LIFE_REPORT"],
        **COMMERCIAL_GATE_3,
    )
    project = _case_probe_project(
        name="Yuzu Sparkling Water", category="BEVERAGE",
    )

    shelf_life = _add_checklist_item(
        api, project["id"], gate3["id"], "SHELF_LIFE_REPORT", "QUALITY", gate_chair_headers
    )
    submit_deliverable(
        shelf_life["id"], evidence_url="https://npd.example/dn/bev-shelf-life",
        submitter_user_id="sub-dn",
    )
    approved = decide_deliverable(shelf_life["id"], "APPROVE", decider_user_id="rev-dn")
    response = api.get_launch_readiness(project["id"], gate_chair_headers)
    readiness = validate_success(response, 200)

    assert approved["status"] == "APPROVED"
    assert response.status_code == 200, "a zero denominator is guarded, not an error"
    assert readiness["launch_readiness_pct"] == pytest.approx(0.00, abs=0.01), (
        "no readiness type is required, so the denominator is zero"
    )
    assert readiness["blocking_deliverable_types"] == []
    assert read_project(project["id"])["launch_readiness_pct"] == pytest.approx(0.00, abs=0.01)


def test_post_launch_continue_and_fix_floors_are_inclusive(
    api, portfolio_admin_headers, gate_chair_headers
):
    """Against a plan of 40000.00 units, 90.00 continues, 70.00 only fixes, 69.99 stops it.

    PRD: "The `decision` follows from `attainment_pct` against two floors: `CONTINUE` when it
    is at least `90.00`, `FIX` when it is at least `70.00` but below `90.00`, and
    `DISCONTINUE` when it is below `70.00`."

    Design: Corner/calculations/calc_post_launch_decision_floors_are_inclusive
    """
    context = setup_launched_project(
        category="SNACK",
        project_type="LINE_EXTENSION",
        project_overrides=dict(SNACK_PROJECT, name="Toffee Crunch Bites Attainment"),
        case_overrides=PLAN_OF_FORTY_THOUSAND_CASE,
        line_overrides=PLAN_OF_FORTY_THOUSAND_LINE,
    )
    project_id = context["project"]["id"]
    locked_case = validate_success(
        api.get_business_case(context["business_case"]["id"], gate_chair_headers)
    )

    period_1 = validate_success(
        api.create_post_launch_period(
            project_id,
            post_launch_period_payload(
                1, actual_units=36000, actual_net_revenue_usd=162000.00,
                actual_gross_margin_usd=72000.00, attainment_basis="TRAILING",
            ),
            portfolio_admin_headers,
        ),
        201,
    )
    after_1 = read_project(project_id)
    period_2 = validate_success(
        api.create_post_launch_period(
            project_id,
            post_launch_period_payload(
                2, actual_units=28000, actual_net_revenue_usd=126000.00,
                actual_gross_margin_usd=56000.00, attainment_basis="TRAILING",
            ),
            portfolio_admin_headers,
        ),
        201,
    )
    after_2 = read_project(project_id)
    period_3 = validate_success(
        api.create_post_launch_period(
            project_id,
            post_launch_period_payload(
                3, actual_units=27996, actual_net_revenue_usd=125982.00,
                actual_gross_margin_usd=55992.00, attainment_basis="TRAILING",
            ),
            portfolio_admin_headers,
        ),
        201,
    )
    after_3 = read_project(project_id)
    presentation = validate_success(
        api.get_sell_in_presentation(context["presentation"]["id"], gate_chair_headers)
    )

    assert locked_case["annual_units"] == 160000
    assert locked_case["status"] == "LOCKED"
    for period in (period_1, period_2, period_3):
        assert_post_launch_period(period)
        assert_attainment_decision(period)
        assert period["plan_units_per_period"] == pytest.approx(40000.00, abs=0.01), (
            "160000 annual units over four periods"
        )
    assert period_1["attainment_pct"] == pytest.approx(90.00, abs=0.01)
    assert period_1["decision"] == "CONTINUE", "the 90.00 floor is inclusive"
    assert after_1["dev_status"] == "LAUNCHED", "a CONTINUE leaves a launched project alone"
    assert period_2["attainment_pct"] == pytest.approx(70.00, abs=0.01)
    assert period_2["decision"] == "FIX", "70.00 is not yet a discontinue"
    assert after_2["dev_status"] == "IN_MARKET_FIX"
    assert period_3["attainment_pct"] == pytest.approx(69.99, abs=0.01)
    assert period_3["decision"] == "DISCONTINUE", "four units below the floor stops it"
    assert period_3["attainment_cumulative_pct"] == pytest.approx(76.66, abs=0.01), (
        "the cumulative reading is stored too, but the TRAILING basis is what decides"
    )
    assert after_3["dev_status"] == "DISCONTINUED"
    assert after_3["post_launch_decision"] == "DISCONTINUE"
    assert after_3["commercial_status"] == "SHIPPED"
    assert presentation["status"] == "ACCEPTED", (
        "discontinuation leaves an accepted authorisation on the record"
    )
