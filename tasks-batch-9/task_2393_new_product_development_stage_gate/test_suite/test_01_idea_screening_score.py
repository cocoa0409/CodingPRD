"""Gate 1 idea screening: the weighted score, the margin clamp and the pass floor."""
import pytest

from test_helpers import (
    assert_project,
    intake_project,
    register_stage_gate,
    set_clock,
    validate_paginated,
    validate_success,
)

IDENTICAL_RATINGS = {
    "category": "BEVERAGE",
    "strategic_fit_score": 8,
    "consumer_need_score": 7,
    "target_gross_margin_pct": 36,
    "category_attractiveness_score": 7,
}


def test_identical_ratings_score_differently_under_each_innovation_type(api, gate_chair_headers):
    """Three ideas with identical intake ratings score 78.00, 79.00 and 77.00.

    PRD: "Identical intake ratings therefore produce different scores under different
    innovation types, which is intentional: a line extension is judged more on margin, a
    renovation more on consumer need."

    Design: Difficulty/combinatorial_formula/screening_weight_vector_with_capped_margin_norm
    """
    set_clock("2026-08-03T00:00:00Z")
    register_stage_gate(
        gate_number=2,
        category="BEVERAGE",
        required_deliverable_types=[
            "CONSUMER_CONCEPT_TEST",
            "PRELIM_BUSINESS_CASE",
            "FINAL_BUSINESS_CASE",
            "PILOT_SCALE_UP_REPORT",
            "SHELF_LIFE_REPORT",
            "REGULATORY_CLEARANCE",
        ],
        quorum_size=3,
        veto_functions=["FINANCE", "QUALITY"],
        npv_hurdle_usd=500000.00,
        payback_months_max=24,
        gross_margin_floor_pct=45.00,
        readiness_floor_index=70.00,
    )

    expected = {"NEW_BRAND": 78.00, "LINE_EXTENSION": 79.00, "RENOVATION": 77.00}
    scores = {}
    for project_type in expected:
        project = intake_project(
            name=f"Weight Vector Probe {project_type}",
            project_type=project_type,
            **IDENTICAL_RATINGS,
        )
        screened = validate_success(
            api.screen_project(
                project["id"],
                {"screening_notes": "Identical ratings, different weight vector"},
                gate_chair_headers,
            )
        )
        assert_project(screened)
        scores[project_type] = screened["screening_score"]
        assert screened["screening_decision"] == "PASSED"
        assert screened["dev_status"] == "SCREENED"

    for project_type, want in expected.items():
        assert scores[project_type] == pytest.approx(want, abs=0.01), (
            f"{project_type} weights must produce {want}, got {scores[project_type]}"
        )
    assert len(set(scores.values())) == 3, (
        "the same four ratings must resolve to three distinct scores"
    )


def test_new_brand_weighting_leans_on_fit_and_consumer_need(api, gate_chair_headers):
    """A NEW_BRAND idea rated 8 / 7 / 36% / 7 scores exactly 78.00.

    PRD: "- `NEW_BRAND` weights them 0.30, 0.30, 0.25 and 0.15."

    Design: Difficulty/combinatorial_formula/screening_weight_vector_with_capped_margin_norm
    """
    set_clock("2026-08-03T00:00:00Z")
    register_stage_gate(gate_number=2, category="BEVERAGE")
    project = intake_project(
        name="Weight Vector Probe NEW_BRAND", project_type="NEW_BRAND", **IDENTICAL_RATINGS
    )

    screened = validate_success(
        api.screen_project(project["id"], {}, gate_chair_headers)
    )

    assert_project(screened)
    assert screened["screening_score"] == pytest.approx(78.00, abs=0.01), (
        "0.30*80 + 0.30*70 + 0.25*90 + 0.15*70 = 78.00"
    )
    assert screened["screening_decision"] == "PASSED"
    assert screened["dev_status"] == "SCREENED"
    assert screened["next_gate_number"] == 2


def test_line_extension_weighting_lifts_the_margin_criterion(api, gate_chair_headers):
    """The same ratings under LINE_EXTENSION weights score 79.00, one point higher.

    PRD: "- `LINE_EXTENSION` weights them 0.30, 0.25, 0.30 and 0.15."

    Design: Difficulty/combinatorial_formula/screening_weight_vector_with_capped_margin_norm
    """
    set_clock("2026-08-03T00:00:00Z")
    register_stage_gate(gate_number=2, category="BEVERAGE")
    project = intake_project(
        name="Weight Vector Probe LINE_EXTENSION",
        project_type="LINE_EXTENSION",
        **IDENTICAL_RATINGS,
    )

    screened = validate_success(
        api.screen_project(project["id"], {}, gate_chair_headers)
    )

    assert screened["screening_score"] == pytest.approx(79.00, abs=0.01), (
        "0.30*80 + 0.25*70 + 0.30*90 + 0.15*70 = 79.00"
    )
    assert screened["screening_score"] != pytest.approx(78.00, abs=0.001), (
        "the line extension vector must not reuse the new brand vector"
    )
    assert screened["dev_status"] == "SCREENED"


def test_margin_normalisation_is_capped_at_one_hundred(api, gate_chair_headers):
    """A 60 percent margin target earns no more than a 40 percent target normalised to 100.

    PRD: "First the margin criterion is normalised: `target_gross_margin_pct` is divided by
    the reference target of 40 percent, multiplied by 100, rounded half up to four decimal
    places, and then capped at 100 — so a project targeting a 60 percent gross margin
    normalises to 100 rather than 150, and the extra ambition earns nothing."

    Design: Difficulty/combinatorial_formula/screening_weight_vector_with_capped_margin_norm
    """
    set_clock("2026-08-03T00:00:00Z")
    register_stage_gate(gate_number=2, category="BEVERAGE")
    project = intake_project(
        name="Margin Cap Probe",
        project_type="NEW_BRAND",
        category="BEVERAGE",
        strategic_fit_score=7,
        consumer_need_score=8,
        target_gross_margin_pct=60,
        category_attractiveness_score=6,
    )

    screened = validate_success(
        api.screen_project(
            project["id"], {"screening_notes": "Margin ambition beyond the reference"},
            gate_chair_headers,
        )
    )

    assert screened["screening_score"] == pytest.approx(79.00, abs=0.01), (
        "0.30*70 + 0.30*80 + 0.25*100 + 0.15*60 = 79.00 once the margin term is capped"
    )
    assert screened["screening_score"] != pytest.approx(91.50, abs=0.001), (
        "an uncapped 150 margin norm would have produced 91.50"
    )
    assert screened["screening_decision"] == "PASSED"


def test_screening_score_exactly_at_the_pass_floor_admits_the_idea(api, gate_chair_headers):
    """A 24 percent margin target lands the score on 60.00 and the idea passes.

    PRD: "The screening floor is `60.00`. When `screening_score` is at least `60.00`,
    `screening_decision` becomes `PASSED` and `dev_status` advances `IDEA → SCREENED`; a
    score one cent below the floor sets `screening_decision` to `REJECTED` and moves
    `dev_status` `IDEA → KILLED` instead."

    Design: Difficulty/boundary_precision_check/screening_score_at_pass_floor_versus_one_hundredth_below
    """
    set_clock("2026-08-03T00:00:00Z")
    gate = register_stage_gate(
        gate_number=2, category="BEVERAGE",
        required_deliverable_types=["CONSUMER_CONCEPT_TEST"],
    )
    project = intake_project(
        name="Floor Exact",
        project_type="LINE_EXTENSION",
        category="BEVERAGE",
        strategic_fit_score=6,
        consumer_need_score=6,
        target_gross_margin_pct=24,
        category_attractiveness_score=6,
    )

    screened = validate_success(
        api.screen_project(
            project["id"], {"screening_notes": "Exactly at the floor"}, gate_chair_headers
        )
    )

    assert screened["screening_score"] == pytest.approx(60.00, abs=0.01)
    assert screened["screening_decision"] == "PASSED"
    assert screened["dev_status"] == "SCREENED"
    items, meta = validate_paginated(
        api.list_deliverables(
            gate_chair_headers, params={"project_id": project["id"], "gate_id": gate["id"]}
        )
    )
    assert meta["total_count"] == 1, "the passing branch builds the gate 2 checklist"
    assert items[0]["deliverable_type"] == "CONSUMER_CONCEPT_TEST"
    assert items[0]["status"] == "PENDING"


def test_screening_score_one_hundredth_below_the_floor_kills_the_idea(api, gate_chair_headers):
    """Trimming the margin target to 23.99 percent scores 59.99 and kills the idea.

    PRD: "The screening floor is `60.00`. When `screening_score` is at least `60.00`,
    `screening_decision` becomes `PASSED` and `dev_status` advances `IDEA → SCREENED`; a
    score one cent below the floor sets `screening_decision` to `REJECTED` and moves
    `dev_status` `IDEA → KILLED` instead."

    Design: Difficulty/boundary_precision_check/screening_score_at_pass_floor_versus_one_hundredth_below
    """
    set_clock("2026-08-03T00:00:00Z")
    gate = register_stage_gate(
        gate_number=2, category="BEVERAGE",
        required_deliverable_types=["CONSUMER_CONCEPT_TEST"],
    )
    project = intake_project(
        name="Floor Minus One Hundredth",
        project_type="LINE_EXTENSION",
        category="BEVERAGE",
        strategic_fit_score=6,
        consumer_need_score=6,
        target_gross_margin_pct=23.99,
        category_attractiveness_score=6,
    )

    screened = validate_success(
        api.screen_project(
            project["id"], {"screening_notes": "One hundredth below the floor"},
            gate_chair_headers,
        )
    )

    assert screened["screening_score"] == pytest.approx(59.99, abs=0.01), (
        "23.99 / 40 * 100 = 59.9750 carries a 0.01 loss into the weighted sum"
    )
    assert screened["screening_decision"] == "REJECTED"
    assert screened["dev_status"] == "KILLED"
    _, meta = validate_paginated(
        api.list_deliverables(
            gate_chair_headers, params={"project_id": project["id"], "gate_id": gate["id"]}
        )
    )
    assert meta["total_count"] == 0, "on the killing branch no checklist is created at all"
