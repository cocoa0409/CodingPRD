"""The decision bar is drawn at the scheduling act alone: the officer who pressed confirm is barred
from the decision, while the officer who registered the camp, opened the cycle and opened the visit
row is not barred at all."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_pct
from test_helpers.test_users import (
    OFFICER_ONE_HEADERS,
    OFFICER_ONE_ID,
    OFFICER_TWO_HEADERS,
    OFFICER_TWO_ID,
    make_officer_headers,
)
from test_helpers.types import (
    AccreditationStatus,
    CampType,
    CycleStatus,
    DecisionLevel,
    HealthStaffingLevel,
    PopulationServed,
    SelfScore,
    StandardDomain,
    VisitStatus,
)
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

DUTIES_STANDARDS = [
    fx.universal_mandatory_standard(
        "SU.1", domain=StandardDomain.SUPERVISION, scoring_weight=1
    )
]

THIRD_OFFICER_ID = "officer-3"
THIRD_OFFICER_HEADERS = make_officer_headers(THIRD_OFFICER_ID)


def _a_cycle_awaiting_a_decision_someone_else_must_make(api):
    """The first officer builds everything and the second officer alone presses confirm."""
    fx.reset_clock(api)
    scenario = fx.open_cycle_scenario(
        api,
        edition_code="ACA-2026-SOD",
        standards=DUTIES_STANDARDS,
        camp={
            "name": "Duties Camp",
            "camp_type": CampType.DAY,
            "state_code": "OH",
            "population_served": PopulationServed.YOUTH_ONLY,
            "health_staffing_level": HealthStaffingLevel.RN_ONSITE,
        },
        self_scores={"SU.1": SelfScore.MET},
        submit=True,
    )
    fx.seat_team(
        api,
        scenario,
        window=("2026-08-01", "2026-08-07"),
        travel=("2026-08-01", "2026-08-03"),
    )
    fx.confirm_visit(api, scenario.visit_id, OFFICER_TWO_HEADERS)
    fx.score_visit(
        api,
        scenario,
        visitor_scores={"SU.1": fx.ALL_MET_OBSERVED},
        clock=None,
    )
    return scenario.refresh(api)


def test_confirmation_stamps_the_officer_who_pressed_it_and_nobody_else(api):
    """PRD §3.5: "Confirmation is an officer act with no body, moving the visit `DRAFT →
    SCHEDULED`, stamping `scheduled_by_user_id` with the acting `X-User-ID` — the value the
    segregation-of-duties rule will later compare against — and driving the cycle `SELF_ASSESSMENT
    → VISIT_SCHEDULED`."

    Design: Corner/rbac/the_officer_who_scheduled_the_visit_cannot_also_issue_the_decision
    """
    scenario = _a_cycle_awaiting_a_decision_someone_else_must_make(api)

    visit = fx.read_visit(api, scenario.visit_id)
    # The first officer opened the visit row; the second officer confirmed it.
    assert visit["scheduled_by_user_id"] == OFFICER_TWO_ID
    assert visit["status"] == VisitStatus.SCORED
    assert fx.read_cycle(api, scenario.cycle_id)["status"] == CycleStatus.VISIT_COMPLETED


def test_the_officer_who_confirmed_the_visit_is_refused_the_decision(api):
    """PRD §2.1: "The officer who confirmed a visit is barred from issuing that cycle's decision:
    when a decision is requested and the acting `X-User-ID` equals the `scheduled_by_user_id`
    recorded on the cycle's visit, the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP
    403)."

    Design: Corner/rbac/the_officer_who_scheduled_the_visit_cannot_also_issue_the_decision
    """
    scenario = _a_cycle_awaiting_a_decision_someone_else_must_make(api)

    validate_error(
        api.issue_decision(scenario.cycle_id, OFFICER_TWO_HEADERS),
        ApiErrorId.SEGREGATION_OF_DUTIES,
        403,
    )

    held = fx.read_cycle(api, scenario.cycle_id)
    assert held["status"] == CycleStatus.VISIT_COMPLETED
    assert held["decision_level"] is None
    assert held["decision_issued_at"] is None
    assert held["decision_issued_by_user_id"] is None


def test_an_officer_who_never_touched_the_cycle_may_decide_it(api):
    """PRD §3.7: "Its three preconditions are the cycle sitting in `VISIT_COMPLETED`
    (`ERR_CYCLE_NOT_IN_SELF_ASSESSMENT`), the acting `X-User-ID` differing from the
    `scheduled_by_user_id` of the cycle's visit (`ERR_SEGREGATION_OF_DUTIES`), and the cycle
    carrying exactly one non-rescinded visit whose `status` is `SCORED`."

    Design: Corner/rbac/the_officer_who_scheduled_the_visit_cannot_also_issue_the_decision
    """
    scenario = _a_cycle_awaiting_a_decision_someone_else_must_make(api)

    decided = validate_success(api.issue_decision(scenario.cycle_id, THIRD_OFFICER_HEADERS))
    assert decided["status"] == CycleStatus.CLOSED
    assert_pct(decided["final_mandatory_pct"], 100.00)
    assert_pct(decided["final_weighted_pct"], 100.00)
    assert decided["decision_level"] == DecisionLevel.ACCREDITED
    assert decided["decision_issued_by_user_id"] == THIRD_OFFICER_ID
    assert is_iso8601_timestamp(decided["decision_issued_at"])

    assert (
        fx.read_camp(api, scenario.camp_id)["accreditation_status"]
        == AccreditationStatus.ACCREDITED
    )
    assert fx.list_deficiencies_for_visit(api, scenario.visit_id)[1]["total_count"] == 0


def test_building_the_cycle_is_no_bar_because_only_the_confirm_stamp_is_compared(api):
    """PRD §2.1: "The server records it — as `scheduled_by_user_id` on `AccreditationVisit`, as
    `decision_issued_by_user_id` on `AccreditationCycle`, and as `reviewer_user_id` on
    `WrittenPlan` and on `Deficiency` — but never compares it to any entity's `id`."

    Design: Corner/rbac/the_officer_who_scheduled_the_visit_cannot_also_issue_the_decision
    """
    scenario = _a_cycle_awaiting_a_decision_someone_else_must_make(api)

    # The first officer registered the camp, opened the cycle and opened the visit row, and is
    # still free to decide, because the comparison is against the confirmation stamp alone.
    decided = validate_success(api.issue_decision(scenario.cycle_id, OFFICER_ONE_HEADERS))
    assert decided["decision_issued_by_user_id"] == OFFICER_ONE_ID
    assert decided["decision_level"] == DecisionLevel.ACCREDITED
    assert decided["status"] == CycleStatus.CLOSED

    rows, meta = validate_paginated(
        api.list_cycles({"camp_id": scenario.camp_id}, OFFICER_ONE_HEADERS)
    )
    assert meta["total_count"] == 1
    assert rows[0]["decision_issued_by_user_id"] == OFFICER_ONE_ID
