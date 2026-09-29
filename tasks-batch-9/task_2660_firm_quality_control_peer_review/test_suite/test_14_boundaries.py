"""Boundary-precision tests for three exact figures.

The PRD pins three thresholds to the cent or to the day: must-select coverage
reads exactly 100.00 on an empty eligible set (PRD 3.6), cooling-off is
inclusive at 730 calendar days (PRD 3.4), and remediation acceptance is
inclusive at exactly 7.00 (PRD 3.8).  Each is probed on both sides.
"""
from typing import Any, Dict

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_fields,
    created_entity,
    read_entity,
)
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.test_users import make_managing_partner_headers, make_qc_director_headers


def _run_selector(api, ctx, inspection_id: str) -> None:
    """Run the deterministic engagement selector for a cycle (setup only)."""
    response = api.run_inspection_selector(inspection_id, headers=ctx["qc_headers"])
    assert response.status_code in (200, 201), (
        f"selector run failed: {response.status_code} {response.text}"
    )


def _rows(response) -> Dict[str, Any]:
    validate_success(response)
    return response.json()


# ---------------------------------------------------------------------------
# Boundary 1 - the empty eligible set reads exactly 100.00 coverage
# ---------------------------------------------------------------------------
def _stage_empty_inspection_cycle(api) -> Dict[str, Any]:
    """A firm with no engagements at all, whose 2024 cycle has run its selector."""
    fixtures.set_clock(api, DEFAULT_CLOCK)
    firm = fixtures.new_firm(api, legal_name="Quillon Marsh LLP")
    qc = fixtures.new_partner(
        api, firm["id"], full_name="Quinn Cade", designations=["QC_DIRECTOR"]
    )
    ctx = {
        "firm_id": firm["id"],
        "qc": qc,
        "qc_headers": make_qc_director_headers(qc["id"]),
    }
    inspection = fixtures.new_inspection(
        api, ctx, inspection_year=2024, target_engagement_count=3
    )
    _run_selector(api, ctx, inspection["id"])
    return {"ctx": ctx, "firm": firm, "inspection": inspection}


def test_empty_eligible_set_reads_100_00_coverage_and_blocks_fieldwork(api):
    """With nothing window-eligible the coverage percentage is exactly 100.00, yet
    opening the cycle for findings is refused because nothing was selected.

    "Advancing SELECTION_COMPLETE -> IN_PROGRESS opens the cycle for findings and
    requires engagements_selected_count to be at least 1; a cycle whose selector
    produced nothing is refused with ERR_NO_ELIGIBLE_ENGAGEMENTS."

    Design: Difficulty/boundary_precision_check/must_select_coverage_reads_exactly_100_00_on_the_empty_eligible_set
    """
    world = _stage_empty_inspection_cycle(api)
    ctx = world["ctx"]
    inspection_id = world["inspection"]["id"]

    refused = api.create_inspection_transition(
        inspection_id, f.inspection_transition_payload("IN_PROGRESS"),
        headers=ctx["qc_headers"],
    )
    validate_error(refused, E.ERR_NO_ELIGIBLE_ENGAGEMENTS, 409)

    cycle = read_entity(
        api.get_internal_inspection(inspection_id, headers=ctx["qc_headers"])
    )
    assert_fields(
        cycle,
        engagements_selected_count=0,
        must_select_eligible_count=0,
        must_select_selected_count=0,
        state="SELECTION_COMPLETE",
    )
    assert_decimal_equals(cycle["must_select_coverage_pct"], 100.00)

    listing = _rows(
        api.list_inspection_selections(
            headers=ctx["qc_headers"], params={"inspection_id": inspection_id}
        )
    )
    assert listing["meta"]["total_count"] == 0, (
        f"expected 0 selections, got {listing['meta']['total_count']}"
    )
    assert listing["data"] == []


def test_empty_cycle_concludes_straight_from_selection_complete_at_zero_index(api):
    """The 100.00 coverage lets an empty cycle close directly, stamping a severity
    index of exactly 0.00 under the engagement-weighted basis.

    "from SELECTION_COMPLETE it may go straight to CONCLUDED provided
    engagements_selected_count is 0 and must_select_coverage_pct is 100.00 ... and
    that leg sets deficiency_severity_index to 0.00 with severity_index_basis
    ENGAGEMENT_WEIGHTED and stamps concluded_at from the logical clock."

    Design: Difficulty/boundary_precision_check/must_select_coverage_reads_exactly_100_00_on_the_empty_eligible_set
    """
    world = _stage_empty_inspection_cycle(api)
    ctx = world["ctx"]
    inspection_id = world["inspection"]["id"]

    refused = api.create_inspection_transition(
        inspection_id, f.inspection_transition_payload("IN_PROGRESS"),
        headers=ctx["qc_headers"],
    )
    validate_error(refused, E.ERR_NO_ELIGIBLE_ENGAGEMENTS, 409)

    concluded = read_entity(
        api.create_inspection_transition(
            inspection_id, f.inspection_transition_payload("CONCLUDED"),
            headers=ctx["qc_headers"],
        )
    )
    assert_fields(
        concluded,
        state="CONCLUDED",
        severity_index_basis="ENGAGEMENT_WEIGHTED",
        engagements_selected_count=0,
    )
    assert_decimal_equals(concluded["deficiency_severity_index"], 0.00)
    assert_decimal_equals(concluded["must_select_coverage_pct"], 100.00)
    assert concluded["concluded_at"] is not None, "concluded_at must be stamped"


# ---------------------------------------------------------------------------
# Boundary 2 - cooling-off is inclusive at 730 calendar days, 729 is refused
# ---------------------------------------------------------------------------
def _stage_cooling_off_boundary_world(api) -> Dict[str, Any]:
    """One candidate reviewer whose two prior clients sit one day apart across the
    730-day floor, against two otherwise identical FIELDWORK engagements."""
    fixtures.set_clock(api, DEFAULT_CLOCK)
    ctx = fixtures.firm_context(api, legal_name="Rushmere Kell LLP")
    reviewer = fixtures.add_eq_reviewer(
        api,
        ctx,
        full_name="Sable Ord",
        prior_engagement_team_clients=[
            {"client_name": "Kite Co", "exit_date": "2022-07-01"},
            {"client_name": "Marlow Co", "exit_date": "2022-07-02"},
        ],
    )
    at_floor = fixtures.new_engagement(
        api, ctx, client_name="Kite Co", engagement_type="AUDIT",
        period_end="2024-06-30",
    )
    at_floor = fixtures.workflow_step(api, at_floor, "FIELDWORK", ctx["ep_headers"])
    below_floor = fixtures.new_engagement(
        api, ctx, client_name="Marlow Co", engagement_type="AUDIT",
        period_end="2024-06-30",
    )
    below_floor = fixtures.workflow_step(
        api, below_floor, "FIELDWORK", ctx["ep_headers"]
    )
    return {
        "ctx": ctx,
        "reviewer": reviewer,
        "at_floor": at_floor,
        "below_floor": below_floor,
    }


def _assign(api, ctx, engagement: Dict[str, Any], reviewer_id: str):
    return api.assign_quality_review(
        engagement["id"],
        f.quality_review_assignment_payload(reviewer_id, engagement["version"]),
        headers=ctx["qc_headers"],
    )


def test_cooling_off_of_exactly_730_days_is_accepted(api):
    """A separation of exactly 730 calendar days between exit_date and period_end
    satisfies the cooling-off floor and is recorded on the review.

    "that separation must be at least 730 days - two full years counted in days,
    where exactly 730 days passes and 729 fails."

    Design: Difficulty/boundary_precision_check/cooling_off_730_days_passes_while_729_days_is_refused
    """
    world = _stage_cooling_off_boundary_world(api)
    ctx = world["ctx"]

    eqr = created_entity(
        _assign(api, ctx, world["at_floor"], world["reviewer"]["id"])
    )
    assert_fields(eqr, state="ASSIGNED", objectivity_attested=True)
    assert eqr["cooling_off_days_at_assignment"] == 730, (
        "2022-07-01 to 2024-06-30 is exactly 730 days, got "
        f"{eqr['cooling_off_days_at_assignment']}"
    )

    reviewer = read_entity(
        api.get_partner(world["reviewer"]["id"], headers=ctx["qc_headers"])
    )
    assert reviewer["open_eqr_count"] == 1


def test_cooling_off_of_729_days_is_refused(api):
    """One day short of the floor - 729 days - is refused, and no review row is
    created for that engagement.

    "If such an entry exists, cooling_off_days_at_assignment is written as the exact
    number of calendar days from that exit_date to the engagement's period_end, and
    that separation must be at least 730 days ... refusing with
    ERR_COOLING_OFF_NOT_MET."

    Design: Difficulty/boundary_precision_check/cooling_off_730_days_passes_while_729_days_is_refused
    """
    world = _stage_cooling_off_boundary_world(api)
    ctx = world["ctx"]

    created_entity(_assign(api, ctx, world["at_floor"], world["reviewer"]["id"]))

    refused = _assign(api, ctx, world["below_floor"], world["reviewer"]["id"])
    validate_error(refused, E.ERR_COOLING_OFF_NOT_MET, 409)

    listing = _rows(
        api.list_quality_reviews(
            headers=ctx["qc_headers"],
            params={"engagement_id": world["below_floor"]["id"]},
        )
    )
    assert listing["meta"]["total_count"] == 0, (
        f"expected 0 quality reviews, got {listing['meta']['total_count']}"
    )
    assert listing["data"] == []

    reviewer = read_entity(
        api.get_partner(world["reviewer"]["id"], headers=ctx["qc_headers"])
    )
    assert reviewer["open_eqr_count"] == 1

    engagement = read_entity(
        api.get_engagement(world["below_floor"]["id"], headers=ctx["qc_headers"])
    )
    assert_fields(engagement, workflow_state="FIELDWORK")


# ---------------------------------------------------------------------------
# Boundary 3 - acceptance is inclusive at exactly 7.00, 6.99 is refused
# ---------------------------------------------------------------------------
def _stage_inspected_engagement(api) -> Dict[str, Any]:
    """A firm whose 2024 cycle is IN_PROGRESS over one selected engagement."""
    fixtures.set_clock(api, DEFAULT_CLOCK)
    ctx = fixtures.firm_context(api, legal_name="Thackery Vole LLP")
    fixtures.released_engagement(
        api, ctx, client_name="Alder Foods", engagement_type="AUDIT",
        period_end="2024-06-30",
    )
    inspection = fixtures.new_inspection(
        api, ctx, inspection_year=2024, target_engagement_count=1
    )
    _run_selector(api, ctx, inspection["id"])
    fixtures.inspection_step(api, ctx, inspection["id"], "IN_PROGRESS")
    selection = fixtures.selections_of(api, ctx, inspection["id"])[0]
    return {"ctx": ctx, "inspection": inspection, "selection": selection}


def _submitted_plan(
    api, world, *, title: str, root_cause_category: str, specificity: float
) -> Dict[str, Any]:
    """Raise a DEFICIENCY, document a 9.00-deep root cause, then plan and submit.

    Four of the five actions are complete, so raw_completeness is
    0.40 * 9.00 + 0.35 * specificity + 0.25 * (10 * 4 / 5).
    """
    ctx = world["ctx"]
    owner = ctx["mp"]
    finding = fixtures.new_finding(
        api, ctx, world["selection"]["id"], title=title,
        sqm_component="ENGAGEMENT_PERFORMANCE",
    )
    classified = fixtures.classify(api, ctx, finding["id"], "DEFICIENCY")
    assert_fields(classified, classification="DEFICIENCY", class_points=3,
                  state="RCA_PENDING")

    fixtures.validated_rca(
        api, ctx, finding["id"], method="FISHBONE",
        root_cause_category=root_cause_category, contributing_factor_count=3,
        narrative="Sampling review was delegated without a documented handover.",
    )
    analyses = _rows(
        api.list_root_cause_analyses(
            headers=ctx["qc_headers"], params={"finding_id": finding["id"]}
        )
    )["data"]
    assert len(analyses) == 1, f"expected 1 analysis, got {len(analyses)}"
    rca = read_entity(
        api.get_root_cause_analysis(analyses[0]["id"], headers=ctx["qc_headers"])
    )
    assert_fields(rca, state="VALIDATED", recurrence_flag=False)
    assert_decimal_equals(rca["depth_score"], 9.00)

    plan = fixtures.new_remediation_plan(
        api, ctx, finding["id"], rca["id"], owner["id"],
        target_completion_date="2026-12-31", action_count=5,
        action_specificity_score=specificity,
    )
    assert_fields(plan, state="DRAFTED", completeness_tier="NONE")

    submitted = read_entity(
        api.create_remediation_plan_transition(
            plan["id"],
            f.remediation_transition_payload("SUBMITTED", completed_action_count=4),
            headers=make_managing_partner_headers(owner["id"]),
        )
    )
    return {"finding": finding, "rca": rca, "plan": plan, "submitted": submitted}


def test_acceptance_score_of_exactly_7_00_is_accepted(api):
    """An acceptance_score landing exactly on 7.00 clears the threshold, stamps
    accepted_at and drives the finding to REMEDIATED.

    "requires acceptance_score to be at least 7.00 - exactly 7.00 is accepted ...
    Acceptance stamps accepted_at from the logical clock and cascades onto the
    finding, driving it REMEDIATION_ASSIGNED -> REMEDIATED; note that a REMEDIATED
    finding is still an open finding, so the firm's open_deficiency_count does not
    move."

    Design: Difficulty/boundary_precision_check/acceptance_threshold_7_00_is_inclusive_while_6_99_is_refused
    """
    world = _stage_inspected_engagement(api)
    ctx = world["ctx"]

    built = _submitted_plan(
        api, world, title="Sampling conclusions not evidenced",
        root_cause_category="SUPERVISION_REVIEW", specificity=4.00,
    )
    submitted = built["submitted"]
    assert_fields(submitted, state="SUBMITTED", completeness_tier="STANDARD",
                  completed_action_count=4, return_count=0)
    assert_decimal_equals(submitted["raw_completeness"], 7.00)
    assert_decimal_equals(submitted["acceptance_score"], 7.00)

    before = read_entity(api.get_firm(ctx["firm_id"], headers=ctx["qc_headers"]))
    assert before["open_deficiency_count"] == 1

    accepted = read_entity(
        api.create_remediation_plan_transition(
            built["plan"]["id"], f.remediation_transition_payload("ACCEPTED"),
            headers=ctx["qc_headers"],
        )
    )
    assert_fields(accepted, state="ACCEPTED", completeness_tier="STANDARD")
    assert_decimal_equals(accepted["acceptance_score"], 7.00)
    assert accepted["accepted_at"] is not None, "accepted_at must be stamped"

    finding = read_entity(
        api.get_inspection_finding(built["finding"]["id"], headers=ctx["qc_headers"])
    )
    assert_fields(finding, state="REMEDIATED")

    firm = read_entity(api.get_firm(ctx["firm_id"], headers=ctx["qc_headers"]))
    assert firm["open_deficiency_count"] == 1, (
        "a REMEDIATED finding is still an open deficiency"
    )


def test_acceptance_score_of_6_99_is_refused(api):
    """One cent short of the threshold - 6.99 - is refused, leaving the plan in
    SUBMITTED with no accepted_at and the finding still merely assigned.

    "6.99 is refused with ERR_ACCEPTANCE_SCORE_BELOW_THRESHOLD."

    Design: Difficulty/boundary_precision_check/acceptance_threshold_7_00_is_inclusive_while_6_99_is_refused
    """
    world = _stage_inspected_engagement(api)
    ctx = world["ctx"]

    built = _submitted_plan(
        api, world, title="Journal entry testing not evidenced",
        root_cause_category="METHODOLOGY_TOOLING", specificity=3.97,
    )
    submitted = built["submitted"]
    assert_fields(submitted, state="SUBMITTED", completeness_tier="STANDARD")
    assert_decimal_equals(submitted["raw_completeness"], 6.99)
    assert_decimal_equals(submitted["acceptance_score"], 6.99)

    refused = api.create_remediation_plan_transition(
        built["plan"]["id"], f.remediation_transition_payload("ACCEPTED"),
        headers=ctx["qc_headers"],
    )
    validate_error(refused, E.ERR_ACCEPTANCE_SCORE_BELOW_THRESHOLD, 409)

    plan = read_entity(
        api.get_remediation_plan(built["plan"]["id"], headers=ctx["qc_headers"])
    )
    assert_fields(plan, state="SUBMITTED", return_count=0)
    assert plan["accepted_at"] is None, "a refused acceptance stamps nothing"
    assert_decimal_equals(plan["acceptance_score"], 6.99)

    finding = read_entity(
        api.get_inspection_finding(built["finding"]["id"], headers=ctx["qc_headers"])
    )
    assert_fields(finding, state="REMEDIATION_ASSIGNED")

    firm = read_entity(api.get_firm(ctx["firm_id"], headers=ctx["qc_headers"]))
    assert firm["open_deficiency_count"] == 1
