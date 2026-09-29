"""Concept-test confidence tiers and the four-part gate readiness index composite."""
import pytest

from test_helpers import (
    add_forecast_line,
    assert_concept_test,
    assert_gate_review,
    book_pilot_run,
    complete_pilot_run,
    create_formulation,
    intake_project,
    open_business_case,
    open_gate_review,
    record_concept_test,
    register_pilot_line,
    register_stage_gate,
    schedule_gate_review,
    screen_project,
    set_clock,
    start_pilot_run,
    validate_paginated,
    validate_success,
)

SNACK_LINE_EXTENSION = {
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
# 0.60 * 80.00 + 0.40 * 40.00 = 64.00 before the confidence multiplier.
STRONG_READ = {
    "test_type": "MONADIC",
    "purchase_intent_top2_pct": 80.00,
    "uniqueness_pct": 40.00,
}
PERMISSIVE_GATE_2 = {
    "gate_number": 2,
    "stage_from": "SCREENED",
    "stage_to": "PILOT_QUALIFIED",
    "required_deliverable_types": [],
    "quorum_size": 1,
    "veto_functions": [],
    "npv_hurdle_usd": 0.00,
    "payback_months_max": 24,
    "gross_margin_floor_pct": 0.00,
    "readiness_floor_index": 0.00,
}
HURDLE_CLEARING_CASE = {
    "variant_mode": "BOTTOM_UP",
    "category_size_units_year": 5000000,
    "target_share_pct": 3.00,
    "cogs_per_unit_usd": 3.2000,
    "slotting_fees_usd": 50000.00,
    "capex_usd": 300000.00,
    "discount_rate_pct": 9.00,
}
HURDLE_CLEARING_LINE = {
    "channel": "GROCERY",
    "store_count": 2400,
    "base_velocity_units_per_store_week": 1.20,
    "promo_weeks": 4,
    "promo_lift_pct": 30.00,
    "list_price_usd": 5.7500,
}


def _concept_probe_project(name="Toffee Crunch Bites", **overrides):
    return intake_project(
        owner_user_id="lead-ct", **dict(SNACK_LINE_EXTENSION, name=name, **overrides)
    )


def _concept_rows(api, project_id, headers):
    """Re-read the whole study set, since recording a newer row rewrites authority."""
    rows, meta = validate_paginated(
        api.list_concept_tests(project_id, headers, params={"limit": 100})
    )
    return {row["id"]: row for row in rows}, meta


def _weight_table_project(name, project_type, category):
    """A screened project rated 9 / 8 / 40 percent / 8 carrying one 64.00 concept read."""
    project = intake_project(
        owner_user_id="lead-rw",
        **dict(
            SNACK_LINE_EXTENSION,
            name=name,
            project_type=project_type,
            category=category,
            strategic_fit_score=9,
            consumer_need_score=8,
            target_gross_margin_pct=40,
            category_attractiveness_score=8,
        ),
    )
    record_concept_test(
        project["id"], sample_size=300, fielded_at="2026-07-01T00:00:00Z", **STRONG_READ
    )
    return screen_project(project["id"], chair_user_id="chair-rw")


def test_one_extra_respondent_at_one_hundred_lifts_the_confidence_tier(
    api, innovation_lead_headers
):
    """99 respondents earn 0.85 and score 54.40; one more earns 0.95 and scores 60.80.

    PRD: "The tier boundaries are inclusive at the bottom: 100 respondents earn the `0.95`
    multiplier while 99 earn only `0.85`, and 300 respondents earn the full `1.00`."

    Design: Corner/calculations/calc_concept_score_confidence_tiers_at_sample_boundaries
    """
    set_clock("2026-08-03T00:00:00Z")
    project = _concept_probe_project()

    at_99 = record_concept_test(
        project["id"], sample_size=99, fielded_at="2026-07-01T00:00:00Z", **STRONG_READ
    )
    at_100 = record_concept_test(
        project["id"], sample_size=100, fielded_at="2026-07-02T00:00:00Z", **STRONG_READ
    )
    rows, meta = _concept_rows(api, project["id"], innovation_lead_headers)

    assert_concept_test(at_99)
    assert_concept_test(at_100)
    assert at_99["concept_score"] == pytest.approx(54.40, abs=0.01), "64.00 * 0.85 = 54.40"
    assert at_100["concept_score"] == pytest.approx(60.80, abs=0.01), "64.00 * 0.95 = 60.80"
    assert at_100["concept_score"] - at_99["concept_score"] == pytest.approx(6.40, abs=0.01), (
        "a single respondent at the tier boundary is worth 6.40 points"
    )
    assert at_99["concept_score"] != pytest.approx(60.80, abs=0.001), (
        "99 respondents must not reach the 0.95 tier"
    )
    assert meta["total_count"] == 2
    assert rows[at_99["id"]]["is_authoritative"] is False
    assert rows[at_100["id"]]["is_authoritative"] is True, (
        "the later fielded_at holds authority"
    )


def test_the_middle_confidence_tier_is_flat_from_one_hundred_to_two_hundred_ninety_nine(
    api, innovation_lead_headers
):
    """199 further respondents inside the 0.95 band move the score not at all.

    PRD: "Purchase intent is weighted 0.60 and uniqueness 0.40; their weighted sum is then
    multiplied by a confidence multiplier chosen from the respondent count — `1.00` when
    `sample_size` is at least 300, `0.95` when `sample_size` is at least 100 but below 300,
    and `0.85` when `sample_size` is below 100 — and the product is rounded half up to two
    decimal places to give `concept_score`."

    Design: Corner/calculations/calc_concept_score_confidence_tiers_at_sample_boundaries
    """
    set_clock("2026-08-03T00:00:00Z")
    project = _concept_probe_project(name="Toffee Crunch Bites Flat Band")

    at_100 = record_concept_test(
        project["id"], sample_size=100, fielded_at="2026-07-02T00:00:00Z", **STRONG_READ
    )
    at_299 = record_concept_test(
        project["id"], sample_size=299, fielded_at="2026-07-03T00:00:00Z", **STRONG_READ
    )
    rows, meta = _concept_rows(api, project["id"], innovation_lead_headers)

    assert at_100["concept_score"] == pytest.approx(60.80, abs=0.01)
    assert at_299["concept_score"] == pytest.approx(60.80, abs=0.01), (
        "299 respondents stay inside the 0.95 band"
    )
    assert at_299["concept_score"] - at_100["concept_score"] == pytest.approx(0.00, abs=0.01), (
        "the multiplier is a step function, not a slope"
    )
    assert at_299["concept_score"] != pytest.approx(64.00, abs=0.001), (
        "one respondent short of 300 earns nothing of the full multiplier"
    )
    assert meta["total_count"] == 2
    assert rows[at_299["id"]]["is_authoritative"] is True
    assert rows[at_100["id"]]["is_authoritative"] is False


def test_three_hundred_respondents_earn_the_full_confidence_and_hold_authority(
    api, innovation_lead_headers
):
    """Four reads at 99, 100, 299 and 300 respondents score 54.40, 60.80, 60.80 and 64.00.

    PRD: "The `is_authoritative` flag is true for exactly one row per project: the study with
    the greatest `fielded_at`, and where several share that instant, the earliest created
    among them."

    Design: Corner/calculations/calc_concept_score_confidence_tiers_at_sample_boundaries
    """
    set_clock("2026-08-03T00:00:00Z")
    project = _concept_probe_project(name="Toffee Crunch Bites Full Ladder")

    created = []
    for sample_size, fielded_at in (
        (99, "2026-07-01T00:00:00Z"),
        (100, "2026-07-02T00:00:00Z"),
        (299, "2026-07-03T00:00:00Z"),
        (300, "2026-07-04T00:00:00Z"),
    ):
        created.append(
            record_concept_test(
                project["id"], sample_size=sample_size, fielded_at=fielded_at, **STRONG_READ
            )
        )
    at_99, at_100, at_299, at_300 = created
    rows, meta = _concept_rows(api, project["id"], innovation_lead_headers)

    assert at_99["concept_score"] == pytest.approx(54.40, abs=0.01)
    assert at_100["concept_score"] == pytest.approx(60.80, abs=0.01)
    assert at_299["concept_score"] == pytest.approx(60.80, abs=0.01)
    assert at_300["concept_score"] == pytest.approx(64.00, abs=0.01), "64.00 * 1.00 = 64.00"
    assert meta["total_count"] == 4, "every read is kept, none is replaced"
    assert rows[at_300["id"]]["is_authoritative"] is True
    assert [
        rows[row["id"]]["is_authoritative"] for row in (at_99, at_100, at_299)
    ] == [False, False, False], "exactly one row per project holds authority"


def test_readiness_index_reads_the_authoritative_concept_test(api, gate_chair_headers):
    """A weak 40.00 first read is displaced, so the index opens on 46.00 and not 40.00.

    PRD: "Only the authoritative study's `concept_score` feeds the gate readiness index of
    §3.6; a project with no study at all contributes `0.00` there."

    Design: Corner/calculations/calc_readiness_index_reads_the_authoritative_concept_test
    """
    set_clock("2026-08-03T00:00:00Z")
    gate2 = register_stage_gate(category="SNACK", **PERMISSIVE_GATE_2)
    project = intake_project(owner_user_id="lead-ac", **SNACK_LINE_EXTENSION)

    weak = record_concept_test(
        project["id"], test_type="MONADIC", sample_size=300,
        purchase_intent_top2_pct=50.00, uniqueness_pct=25.00,
        fielded_at="2026-06-10T00:00:00Z",
    )
    strong = record_concept_test(
        project["id"], test_type="SEQUENTIAL_MONADIC", sample_size=300,
        purchase_intent_top2_pct=80.00, uniqueness_pct=40.00,
        fielded_at="2026-07-15T00:00:00Z",
    )
    screen_project(
        project["id"], chair_user_id="chair-ac",
        screening_notes="Second concept read is the one to bank on.",
    )
    review = schedule_gate_review(
        project["id"], gate2["id"], chair_user_id="chair-ac",
        scheduled_at="2026-08-12T09:00:00Z",
    )
    opened = open_gate_review(review["id"], chair_user_id="chair-ac")
    rows, meta = _concept_rows(api, project["id"], gate_chair_headers)

    assert_gate_review(opened)
    assert weak["concept_score"] == pytest.approx(40.00, abs=0.01), "0.6*50 + 0.4*25 = 40.00"
    assert strong["concept_score"] == pytest.approx(64.00, abs=0.01)
    assert rows[weak["id"]]["is_authoritative"] is False
    assert rows[strong["id"]]["is_authoritative"] is True
    assert opened["deliverable_completeness_pct"] == pytest.approx(100.00, abs=0.01), (
        "an empty required checklist is vacuously complete"
    )
    assert opened["readiness_index"] == pytest.approx(46.00, abs=0.01), (
        "0.30 * 100.00 + 0.25 * 64.00 with hurdle and yield both 0.00"
    )
    assert opened["readiness_index"] != pytest.approx(40.00, abs=0.001), (
        "the superseded first read would have produced 40.00"
    )
    assert meta["total_count"] == 2, "the weak row was displaced, not deleted"


def test_readiness_index_is_capped_at_one_hundred_after_the_household_factor(
    api, gate_chair_headers
):
    """A perfect HOUSEHOLD renovation would reach 105.00 uncapped and stores 100.00.

    PRD: "The weighted sum is then multiplied by a category adjustment factor — `1.00` for
    `BEVERAGE`, `1.00` for `SNACK`, `0.95` for `DAIRY`, `1.05` for `HOUSEHOLD` — and the
    product is rounded half up to two decimal places **once, after the category factor is
    applied**, then capped at `100.00`."

    Design: Corner/calculations/calc_readiness_index_capped_at_one_hundred
    """
    set_clock("2026-08-03T00:00:00Z")
    gate2 = register_stage_gate(category="HOUSEHOLD", **PERMISSIVE_GATE_2)
    pilot_line = register_pilot_line(
        plant_name="Toledo", line_code="TOL-9", allergen_regime="NONE"
    )
    project = intake_project(
        owner_user_id="lead-cap",
        **dict(
            SNACK_LINE_EXTENSION,
            name="Citrus Surface Spray",
            brand="BrightHome",
            category="HOUSEHOLD",
            project_type="RENOVATION",
        ),
    )
    concept = record_concept_test(
        project["id"], test_type="IN_HOME_USE", sample_size=300,
        purchase_intent_top2_pct=100.00, uniqueness_pct=100.00,
        fielded_at="2026-07-01T00:00:00Z",
    )
    screened = screen_project(
        project["id"], chair_user_id="chair-cap",
        screening_notes="Renovation of the core spray line.",
    )
    case = open_business_case(project["id"], **HURDLE_CLEARING_CASE)
    add_forecast_line(case["id"], **HURDLE_CLEARING_LINE)
    formulation = create_formulation(
        project["id"], spec_summary="Citrus solvent blend at 4 percent",
        allergen_regime="NONE", target_shelf_life_days=365, unit_cost_usd=3.2000,
    )
    run = book_pilot_run(
        formulation["id"], pilot_line["id"],
        window_start="2026-08-01T08:00:00Z", window_end="2026-08-01T16:00:00Z",
        planned_units=10000, committed_cost_usd=10000.00,
    )
    start_pilot_run(run["id"])
    run = complete_pilot_run(run["id"], 10000)
    review = schedule_gate_review(
        project["id"], gate2["id"], chair_user_id="chair-cap",
        scheduled_at="2026-08-12T09:00:00Z",
    )
    opened = open_gate_review(review["id"], chair_user_id="chair-cap")
    stored_case = validate_success(api.get_business_case(case["id"], gate_chair_headers))
    stored_formulation = validate_success(
        api.get_formulation(formulation["id"], gate_chair_headers)
    )

    assert screened["screening_score"] == pytest.approx(77.00, abs=0.01)
    assert concept["concept_score"] == pytest.approx(100.00, abs=0.01)
    assert run["yield_pct"] == pytest.approx(100.00, abs=0.01)
    assert stored_formulation["status"] == "PILOT_PASSED"
    assert stored_formulation["best_pilot_yield_pct"] == pytest.approx(100.00, abs=0.01)
    assert stored_case["npv_usd"] == pytest.approx(418503.80, abs=0.01)
    assert stored_case["payback_months"] == 14
    assert stored_case["gross_margin_pct"] == pytest.approx(34.00, abs=0.01), (
        "all three gate hurdles clear, so the hurdle sub-score is 100.00"
    )
    assert opened["deliverable_completeness_pct"] == pytest.approx(100.00, abs=0.01)
    assert opened["readiness_index"] == pytest.approx(100.00, abs=0.01)
    assert opened["readiness_index"] != pytest.approx(105.00, abs=0.001), (
        "the uncapped product of base 100.00 and the HOUSEHOLD factor 1.05 is out of range"
    )


def test_readiness_weight_vector_is_keyed_on_the_innovation_type(api, gate_chair_headers):
    """Two SNACK projects differing only in project_type open on 54.20 and 52.80.

    PRD: "Those four — completeness, concept, hurdle, yield, in that order — are combined
    under a weight vector chosen by the project's `project_type`: `NEW_BRAND` weights them
    0.35, 0.30, 0.20 and 0.15; `LINE_EXTENSION` weights them 0.30, 0.25, 0.25 and 0.20;
    `RENOVATION` weights them 0.40, 0.20, 0.20 and 0.20."

    Design: Corner/calculations/calc_readiness_weight_table_and_category_factor_are_separate_keys
    """
    set_clock("2026-08-03T00:00:00Z")
    snack_gate = register_stage_gate(category="SNACK", **PERMISSIVE_GATE_2)
    new_brand = _weight_table_project("Toffee Crunch Bites", "NEW_BRAND", "SNACK")
    renovation = _weight_table_project("Toffee Crunch Classic", "RENOVATION", "SNACK")

    nb_review = schedule_gate_review(
        new_brand["id"], snack_gate["id"], chair_user_id="chair-rw",
        scheduled_at="2026-08-12T09:00:00Z",
    )
    nb_opened = open_gate_review(nb_review["id"], chair_user_id="chair-rw")
    rn_review = schedule_gate_review(
        renovation["id"], snack_gate["id"], chair_user_id="chair-rw",
        scheduled_at="2026-08-12T10:00:00Z",
    )
    rn_opened = open_gate_review(rn_review["id"], chair_user_id="chair-rw")

    assert new_brand["screening_score"] == pytest.approx(88.00, abs=0.01)
    assert renovation["screening_score"] == pytest.approx(87.00, abs=0.01), (
        "the screening table is a different table from the readiness weights"
    )
    assert nb_opened["deliverable_completeness_pct"] == pytest.approx(100.00, abs=0.01)
    assert rn_opened["deliverable_completeness_pct"] == pytest.approx(100.00, abs=0.01)
    assert nb_opened["readiness_index"] == pytest.approx(54.20, abs=0.01), (
        "0.35 * 100.00 + 0.30 * 64.00 = 54.20"
    )
    assert rn_opened["readiness_index"] == pytest.approx(52.80, abs=0.01), (
        "0.40 * 100.00 + 0.20 * 64.00 = 52.80"
    )
    assert nb_opened["readiness_index"] != rn_opened["readiness_index"], (
        "project_type is the only difference between the two rows"
    )
    assert nb_opened["status"] == "IN_SESSION"
    assert rn_opened["status"] == "IN_SESSION"


def test_category_adjustment_factor_is_applied_once_after_the_weighted_sum(
    api, gate_chair_headers
):
    """The same NEW_BRAND profile reads 54.20 in snack and 51.49 in dairy.

    PRD: "The same project profile therefore scores lower in dairy and higher in household
    than in beverage or snack."

    Design: Corner/calculations/calc_readiness_weight_table_and_category_factor_are_separate_keys
    """
    set_clock("2026-08-03T00:00:00Z")
    snack_gate = register_stage_gate(category="SNACK", **PERMISSIVE_GATE_2)
    dairy_gate = register_stage_gate(category="DAIRY", **PERMISSIVE_GATE_2)
    snack_project = _weight_table_project("Toffee Crunch Bites", "NEW_BRAND", "SNACK")
    dairy_project = _weight_table_project("Toffee Crunch Yogurt", "NEW_BRAND", "DAIRY")

    snack_review = schedule_gate_review(
        snack_project["id"], snack_gate["id"], chair_user_id="chair-rw",
        scheduled_at="2026-08-12T09:00:00Z",
    )
    snack_opened = open_gate_review(snack_review["id"], chair_user_id="chair-rw")
    dairy_review = schedule_gate_review(
        dairy_project["id"], dairy_gate["id"], chair_user_id="chair-rw",
        scheduled_at="2026-08-12T11:00:00Z",
    )
    dairy_opened = open_gate_review(dairy_review["id"], chair_user_id="chair-rw")

    assert snack_opened["readiness_index"] == pytest.approx(54.20, abs=0.01), (
        "the SNACK factor of 1.00 leaves the weighted sum alone"
    )
    assert dairy_opened["readiness_index"] == pytest.approx(51.49, abs=0.01), (
        "54.20 multiplied once by the DAIRY factor 0.95 rounds to 51.49"
    )
    assert dairy_opened["readiness_index"] != pytest.approx(54.20, abs=0.001), (
        "category is the only difference between the two rows"
    )
    assert snack_project["screening_score"] == pytest.approx(88.00, abs=0.01)
    assert dairy_project["screening_score"] == pytest.approx(88.00, abs=0.01), (
        "the category factor touches the readiness index alone, not the screening score"
    )
