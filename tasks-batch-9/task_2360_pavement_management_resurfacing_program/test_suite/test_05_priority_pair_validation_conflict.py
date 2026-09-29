"""Two rules broken by one request; the PRD fixes which one is reported."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_scenario_funding
from test_helpers.constants import FUNDING_STANDARD, MAPLE_TOTAL, OBS_MILL
from test_helpers.factories import (
    award_payload,
    cut_decide_payload,
    schedule_notice_payload,
)
from test_helpers.test_users import ENGINEER, OFFICER_AWARDER


def _coordinating_project(api):
    """A project stuck in COORDINATING with not one utility cleared."""
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_ONLY)
    ctx = fixtures.coordinating_project(api, ctx)
    scenario = fixtures.read_scenario(api, ctx["scenario"]["id"])
    assert_scenario_funding(scenario, FUNDING_STANDARD, 0, FUNDING_STANDARD)
    return ctx


def test_award_state_error_is_reported_over_the_fiscal_errors(api):
    """A coordinating project and a wildly excessive amount report the state error.

    PRD: "First, on an award attempt, the project's own delivery state outranks
    the fiscal check: an award aimed at a project still coordinating, for an
    amount far beyond what the scenario has left uncommitted, reports
    `ERR_PROJECT_NOT_BID_READY` and never `ERR_SCENARIO_FUNDS_EXCEEDED`."

    999999999 cents is roughly fifty times the whole 20000000-cent program and
    also far outside the 10 percent estimate tolerance, so both fiscal rules are
    live and both are suppressed.

    Design: Difficulty/priority_pair_validation_conflict/award_state_error_precedes_funds_exceeded_error
    """
    ctx = _coordinating_project(api)

    error = validate_error(
        api.award_project(
            ctx["project"]["id"],
            award_payload(ctx["contractor"]["id"], 999999999),
            OFFICER_AWARDER,
        ),
        ApiErrorId.PROJECT_NOT_BID_READY,
        409,
    )

    assert error["error_id"] != ApiErrorId.SCENARIO_FUNDS_EXCEEDED
    assert error["error_id"] != ApiErrorId.AWARD_OUTSIDE_ESTIMATE_TOLERANCE


def test_the_rejected_award_moves_no_money_and_no_state(api):
    """The suppressed fiscal rules leave the funding picture exactly as it was.

    PRD: "The funding total always equals committed plus uncommitted, exactly."

    Design: Difficulty/priority_pair_validation_conflict/award_state_error_precedes_funds_exceeded_error
    """
    ctx = _coordinating_project(api)

    validate_error(
        api.award_project(
            ctx["project"]["id"],
            award_payload(ctx["contractor"]["id"], 999999999),
            OFFICER_AWARDER,
        ),
        ApiErrorId.PROJECT_NOT_BID_READY,
        409,
    )

    project = fixtures.read_project(api, ctx["project"]["id"])
    scenario = fixtures.read_scenario(api, ctx["scenario"]["id"])

    assert project["delivery_status"] == "COORDINATING"
    assert project["award_amount_cents"] is None
    assert project["contractor_id"] is None
    assert_scenario_funding(scenario, FUNDING_STANDARD, 0, FUNDING_STANDARD)


def _open_trench_under_an_undelivered_notice(api):
    """An awarded project with an approved open cut and a notice never scheduled."""
    ctx = fixtures.maple_awarded(api)
    segment_id = fixtures.segment_for(ctx, "Maple St")["id"]

    permit = fixtures.apply_cut_permit(
        api,
        segment_id,
        applicant_utility="WATER",
        requested_start="2026-08-05T00:00:00Z",
        requested_end="2026-08-08T00:00:00Z",
        cut_area_sqft=200.0,
        emergency=False,
    )
    assert permit["permit_status"] == "PENDING"
    approved = validate_success(
        api.decide_cut_permit(permit["id"], cut_decide_payload("APPROVE"), ENGINEER)
    )
    assert approved["permit_status"] == "APPROVED"
    assert approved["cut_completed_at"] is None

    line = fixtures.read_line(api, ctx["lines"]["Maple St"]["id"])
    assert line["notice_state"] == "PENDING"
    assert line["work_state"] == "PLANNED"
    return ctx


def test_open_cut_safety_error_is_reported_over_the_notice_error(api):
    """Worker safety outranks notice completeness on the identical action.

    PRD: "Second, on the transition that puts crews on the street, the open-trench
    safety rule outranks the notice-completeness rule: a project holding both an
    open approved trench and an undelivered resident notice reports
    `ERR_OPEN_CUT_ON_SEGMENT` and never `ERR_NOTICES_NOT_DELIVERED`."

    Design: Difficulty/priority_pair_validation_conflict/open_cut_safety_error_precedes_notices_not_delivered_error
    """
    ctx = _open_trench_under_an_undelivered_notice(api)

    error = validate_error(
        api.advance_project(ctx["project"]["id"], {"action": "START_CONSTRUCTION"}, ENGINEER),
        ApiErrorId.OPEN_CUT_ON_SEGMENT,
        409,
    )

    assert error["error_id"] != ApiErrorId.NOTICES_NOT_DELIVERED


def test_the_refused_construction_start_moves_neither_dimension(api):
    """Both the delivery axis and the line's construction axis stand still.

    PRD: "The transition moves every line whose `work_state` is `PLANNED` to
    `IN_PROGRESS`, which makes each line eligible for acceptance testing; because
    both `PLANNED` and `IN_PROGRESS` count as active occupancy, the affected
    segments' `active_project_count` values do not change."

    Design: Difficulty/priority_pair_validation_conflict/open_cut_safety_error_precedes_notices_not_delivered_error
    """
    ctx = _open_trench_under_an_undelivered_notice(api)

    validate_error(
        api.advance_project(ctx["project"]["id"], {"action": "START_CONSTRUCTION"}, ENGINEER),
        ApiErrorId.OPEN_CUT_ON_SEGMENT,
        409,
    )

    assert fixtures.read_project(api, ctx["project"]["id"])["delivery_status"] == "AWARDED"
    assert fixtures.read_line(api, ctx["lines"]["Maple St"]["id"])["work_state"] == "PLANNED"
    assert ctx["award_amount_cents"] == MAPLE_TOTAL


def _sibling_lines_on_one_segment(api):
    """Two projects hold a line each on the same block; the first notice is out."""
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_ONLY)
    ctx = fixtures.draft_project(
        api,
        ctx,
        [("Maple St", "2026-09-01T00:00:00Z", "2026-09-15T00:00:00Z")],
        project_name="Maple St phase 1",
    )
    line_a = ctx["lines"]["Maple St"]
    fixtures.schedule_notice(api, line_a["id"], "2026-09-01T00:00:00Z", "2026-09-15T00:00:00Z")
    delivered = fixtures.deliver_notice(api, line_a["id"])
    assert delivered["notice_state"] == "DELIVERED"

    segment_id = fixtures.segment_for(ctx, "Maple St")["id"]
    later = fixtures.open_survey(api, survey_year=2027)
    observation = fixtures.file_observation(api, later["id"], segment_id, OBS_MILL)
    fixtures.accept_observation(api, observation["id"])
    fixtures.seal_survey(api, later["id"])
    candidate_b = fixtures.generate_candidates(api, later["id"])[0]

    scenario_b = fixtures.create_scenario(
        api, later["id"], scenario_name="FY28 program", funding_cents=FUNDING_STANDARD
    )
    fixtures.run_scenario(api, scenario_b["id"])
    fixtures.adopt_scenario(api, scenario_b["id"])
    project_b = fixtures.create_project(
        api,
        scenario_b["id"],
        "Z1",
        project_name="Maple St phase 2",
        planned_start_date="2026-10-01T00:00:00Z",
        planned_end_date="2026-10-31T00:00:00Z",
    )
    line_b = fixtures.add_line(
        api,
        project_b["id"],
        segment_id,
        candidate_b["id"],
        "2026-10-01T00:00:00Z",
        "2026-10-20T00:00:00Z",
    )
    assert line_b["notice_state"] == "PENDING"
    return line_b


def test_notice_lead_time_error_is_reported_over_the_window_conflict(api):
    """A window that breaks both gates reports the lead-time gate, checked first.

    PRD: "Third, on a notice scheduling or rescheduling action, the lead-time rule
    outranks the window-overlap rule: a window that is both inside the lead time
    and buffered-overlapping a sibling line's window reports
    `ERR_NOTICE_LEAD_TIME_TOO_SHORT` and never `ERR_NOTICE_WINDOW_CONFLICT`."

    2026-08-03 is 48 hours after the clock, and buffered to 2026-08-02..2026-09-06
    the window also overlaps the sibling's buffered 2026-08-31..2026-09-16.

    Design: Difficulty/priority_pair_validation_conflict/notice_lead_time_error_precedes_window_conflict_error
    """
    line_b = _sibling_lines_on_one_segment(api)

    error = validate_error(
        api.notice(
            line_b["id"],
            schedule_notice_payload("2026-08-03T00:00:00Z", "2026-09-05T00:00:00Z"),
            ENGINEER,
        ),
        ApiErrorId.NOTICE_LEAD_TIME_TOO_SHORT,
        422,
    )

    assert error["error_id"] != ApiErrorId.NOTICE_WINDOW_CONFLICT
    line = fixtures.read_line(api, line_b["id"])
    assert line["notice_state"] == "PENDING"
    assert line["parking_restriction_start"] is None


def test_fixing_only_the_lead_time_exposes_the_live_window_conflict(api):
    """The suppressed overlap rule was live all along, on the very same line.

    PRD: "The window, expanded by a 24-hour buffer on each side and compared as a
    **closed** interval, must not overlap the notice window of any other
    non-removed line on the same segment whose `notice_state` is `SCHEDULED` or
    `DELIVERED`; an overlap reports `ERR_NOTICE_WINDOW_CONFLICT`."

    2026-09-10..2026-09-14 clears the 72-hour runway from the 2026-08-01 clock and
    then collides with the sibling line's delivered 2026-09-01..2026-09-15 window.

    Design: Difficulty/priority_pair_validation_conflict/notice_lead_time_error_precedes_window_conflict_error
    """
    line_b = _sibling_lines_on_one_segment(api)
    validate_error(
        api.notice(
            line_b["id"],
            schedule_notice_payload("2026-08-03T00:00:00Z", "2026-09-05T00:00:00Z"),
            ENGINEER,
        ),
        ApiErrorId.NOTICE_LEAD_TIME_TOO_SHORT,
        422,
    )

    validate_error(
        api.notice(
            line_b["id"],
            schedule_notice_payload("2026-09-10T00:00:00Z", "2026-09-14T00:00:00Z"),
            ENGINEER,
        ),
        ApiErrorId.NOTICE_WINDOW_CONFLICT,
        409,
    )

    line = fixtures.read_line(api, line_b["id"])
    assert line["notice_state"] == "PENDING"
    assert line["parking_restriction_start"] is None
    assert line["notice_round"] == 1
