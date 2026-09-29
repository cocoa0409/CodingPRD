"""The correction negotiation on one scored finding: the revision budget burns down without any
office action, the pending plan shelters the finding from the clock, and every late review is
answered by the rule that outranks the others."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import correction_plan_payload, deficiency_review_payload
from test_helpers.test_users import OFFICER_ONE_HEADERS
from test_helpers.types import (
    AccreditationStatus,
    CampType,
    Certification,
    CompliancePosture,
    CycleStatus,
    DecisionLevel,
    DeficiencyDecision,
    DeficiencySeverity,
    DeficiencyStatus,
    HealthStaffingLevel,
    PopulationServed,
    SelfScore,
    StandardDomain,
    TeamRole,
)
from prd_bench_local_runner.testing import validate_error

LATE_STANDARDS = [
    fx.universal_mandatory_standard(
        "SU.1", domain=StandardDomain.SUPERVISION, scoring_weight=1
    ),
    fx.universal_optional_standard("OM.9", domain=StandardDomain.OPERATIONS, scoring_weight=1),
]

LATE_TEAM = [
    {
        "key": "lead",
        "full_name": "Late Lead",
        "home_state_code": "PA",
        "certifications": [Certification.LEAD_VISITOR],
        "team_role": TeamRole.LEAD,
    },
    {
        "key": "member",
        "full_name": "Late Member",
        "home_state_code": "PA",
        "certifications": [],
        "team_role": TeamRole.MEMBER,
    },
]


def _cycle_in_correction_over_one_scored_finding(api):
    """A cycle accredited with correction, carrying a single non-mandatory finding."""
    fx.reset_clock(api)
    scenario = fx.open_cycle_scenario(
        api,
        edition_code="ACA-2026-LTR",
        standards=LATE_STANDARDS,
        camp={
            "name": "Late Review Camp",
            "camp_type": CampType.DAY,
            "state_code": "OH",
            "population_served": PopulationServed.YOUTH_ONLY,
            "health_staffing_level": HealthStaffingLevel.FIRST_AIDER_ONLY,
        },
        self_scores={"SU.1": SelfScore.MET, "OM.9": SelfScore.PARTIAL},
        submit=True,
    )
    fx.seat_team(
        api,
        scenario,
        team=LATE_TEAM,
        window=("2026-08-01", "2026-08-07"),
        travel=("2026-08-01", "2026-08-03"),
        confirm=True,
    )
    fx.score_visit(
        api,
        scenario,
        visitor_scores={"SU.1": fx.ALL_MET_OBSERVED, "OM.9": fx.NOT_MET_OBSERVED},
        clock=None,
    )
    return fx.decide_cycle(api, scenario)


def _the_only_finding(scenario):
    assert len(scenario.deficiencies) == 1
    return scenario.deficiencies[0]


def _plan_attempt(api, scenario, finding_id, text):
    return api.file_correction_plan(
        finding_id, correction_plan_payload(text), scenario.director_headers
    )


def _review_attempt(api, finding_id, decision, note):
    return api.review_deficiency(
        finding_id, deficiency_review_payload(decision, note), OFFICER_ONE_HEADERS
    )


def test_the_correction_deadline_is_set_from_the_latest_due_date_on_the_visit(api):
    """PRD §3.7: "The `IN_CORRECTION` branch instead sets the cycle's `correction_deadline_at`
    to the latest `correction_due_date` among the deficiencies on that visit, expressed at
    23:59:59.999Z on that date."

    Design: Corner/validations/pending_plan_shelters_the_finding_from_escalation_but_late_review_and_a_fourth_plan_are_refused
    """
    scenario = _cycle_in_correction_over_one_scored_finding(api)
    finding = _the_only_finding(scenario)

    assert finding["severity"] == DeficiencySeverity.SCORED
    assert finding["base_points"] == 2
    # A batch base total of 2 selects tier 0: no surcharge and the full ninety-day window.
    assert finding["penalty_points"] == 2
    assert finding["correction_due_date"] == "2026-10-30"
    assert finding["status"] == DeficiencyStatus.OPEN

    assert scenario.cycle["decision_level"] == DecisionLevel.ACCREDITED_WITH_CORRECTION
    assert scenario.cycle["status"] == CycleStatus.IN_CORRECTION
    assert scenario.cycle["correction_deadline_at"] == "2026-10-30T23:59:59.999Z"
    assert scenario.camp["accreditation_status"] == (
        AccreditationStatus.ACCREDITED_WITH_CORRECTION
    )
    assert scenario.camp["penalty_point_balance"] == 2
    assert scenario.camp["compliance_posture"] == CompliancePosture.OPEN

    # VERIFY_CORRECTION demands PLAN_ACCEPTED, and nothing has been filed yet.
    validate_error(
        _review_attempt(
            api, finding["id"], DeficiencyDecision.VERIFY_CORRECTION, "premature verification"
        ),
        ApiErrorId.DEFICIENCY_INVALID_STATE,
        409,
    )


def test_replacing_an_unreviewed_plan_spends_the_revision_budget_to_exhaustion(api):
    """PRD §3.8: "Note the consequence of the self-loop: replacing an unreviewed plan spends
    revision budget with no office action at all, so a camp that files, replaces, and replaces
    again finds the fourth filing refused with `ERR_PLAN_REVISION_LIMIT`."

    Design: Corner/validations/pending_plan_shelters_the_finding_from_escalation_but_late_review_and_a_fourth_plan_are_refused
    """
    scenario = _cycle_in_correction_over_one_scored_finding(api)
    finding_id = _the_only_finding(scenario)["id"]

    first = fx.file_correction_plan(
        api, scenario.camp_id, finding_id, "first plan - rebuild the operations binder"
    )
    assert first["status"] == DeficiencyStatus.PLAN_SUBMITTED
    assert first["plan_revision_count"] == 1

    second = fx.file_correction_plan(
        api, scenario.camp_id, finding_id, "second plan - replaces the first before review"
    )
    assert second["status"] == DeficiencyStatus.PLAN_SUBMITTED
    assert second["plan_revision_count"] == 2

    third = fx.file_correction_plan(
        api, scenario.camp_id, finding_id, "third plan - replaces the second before review"
    )
    assert third["status"] == DeficiencyStatus.PLAN_SUBMITTED
    assert third["plan_revision_count"] == 3
    assert third["correction_plan_text"] == "third plan - replaces the second before review"

    validate_error(
        _plan_attempt(api, scenario, finding_id, "fourth plan - budget exhausted"),
        ApiErrorId.PLAN_REVISION_LIMIT,
        422,
    )

    held = fx.read_deficiency(api, finding_id)
    assert held["plan_revision_count"] == 3
    assert held["correction_plan_text"] == "third plan - replaces the second before review"
    # PLAN_SUBMITTED sits inside the counted set, so the ledger never moved.
    assert fx.read_camp(api, scenario.camp_id)["penalty_point_balance"] == 2


def test_a_pending_plan_is_sheltered_from_the_clock_past_its_due_date(api):
    """PRD §3.8: "A finding sitting in `PLAN_SUBMITTED` past its due date is not escalated by
    the clock at all — the office holds the pending plan — but a review arriving after the date
    is refused with `ERR_CORRECTION_WINDOW_EXPIRED`."

    Design: Corner/validations/pending_plan_shelters_the_finding_from_escalation_but_late_review_and_a_fourth_plan_are_refused
    """
    scenario = _cycle_in_correction_over_one_scored_finding(api)
    finding_id = _the_only_finding(scenario)["id"]
    fx.file_correction_plan(
        api, scenario.camp_id, finding_id, "first plan - rebuild the operations binder"
    )

    advance = fx.set_clock(api, "2026-10-31T00:00:00Z")
    assert advance["escalated_deficiency_count"] == 0
    assert advance["terminated_cycle_count"] == 0

    assert fx.read_deficiency(api, finding_id)["status"] == DeficiencyStatus.PLAN_SUBMITTED
    assert fx.read_cycle(api, scenario.cycle_id)["status"] == CycleStatus.IN_CORRECTION
    camp = fx.read_camp(api, scenario.camp_id)
    assert camp["accreditation_status"] == AccreditationStatus.ACCREDITED_WITH_CORRECTION
    assert camp["penalty_point_balance"] == 2


def test_every_late_review_is_answered_by_the_rule_that_outranks_the_others(api):
    """PRD §3.8: "`WAIVE` requires `OPEN` and is permitted only when the finding's `severity` is
    `SCORED`; waiving a `MANDATORY` or `MANDATORY_CRITICAL` finding is refused with
    `ERR_DEFICIENCY_INVALID_STATE`."

    Design: Corner/validations/pending_plan_shelters_the_finding_from_escalation_but_late_review_and_a_fourth_plan_are_refused
    """
    scenario = _cycle_in_correction_over_one_scored_finding(api)
    finding_id = _the_only_finding(scenario)["id"]
    fx.file_correction_plan(
        api, scenario.camp_id, finding_id, "first plan - rebuild the operations binder"
    )
    fx.set_clock(api, "2026-10-31T00:00:00Z")

    # The status these two decisions demand is satisfied, so the expired window answers.
    validate_error(
        _review_attempt(
            api, finding_id, DeficiencyDecision.ACCEPT_PLAN, "accepted after the deadline"
        ),
        ApiErrorId.CORRECTION_WINDOW_EXPIRED,
        422,
    )
    validate_error(
        _review_attempt(
            api, finding_id, DeficiencyDecision.REJECT_PLAN, "rejected after the deadline"
        ),
        ApiErrorId.CORRECTION_WINDOW_EXPIRED,
        422,
    )
    # WAIVE demands OPEN, and the state precondition is read before the window.
    validate_error(
        _review_attempt(api, finding_id, DeficiencyDecision.WAIVE, "waiver after the deadline"),
        ApiErrorId.DEFICIENCY_INVALID_STATE,
        409,
    )

    held = fx.read_deficiency(api, finding_id)
    assert held["status"] == DeficiencyStatus.PLAN_SUBMITTED
    assert held["plan_revision_count"] == 1
    assert fx.read_camp(api, scenario.camp_id)["penalty_point_balance"] == 2
