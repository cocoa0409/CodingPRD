"""Validation edges on filing an absence, and the contracts of four endpoints.

The absence endpoint carries the densest validation stack in the program: a
closed window, a school calendar reached through three hops, and a uniqueness
rule scoped to non-terminal rows. These tests walk those edges from both sides,
then hold four endpoints to their declared response contracts — the clock
sweep's two counters, the bidirectional link a project forges with a complaint,
and the school's coverage read reconciled against the posts underneath it.
"""
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_absence_report,
    assert_clock_response,
    assert_guard_post,
    assert_infrastructure_project,
    assert_school_coverage_partition,
)
from test_helpers.factories import (
    create_absence_report_payload,
    create_guard_post_payload,
    create_project_payload,
    rescind_absence_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    ENGINEER,
    SUPERVISOR,
    add_second_post_and_guard,
    create_active_post,
    create_grant_program,
    read_absence,
    read_assignment,
    read_complaint,
    read_guard,
    read_intersection,
    read_post,
    read_program,
    read_school,
    setup_finalized_study,
    setup_staffed_post,
    setup_triaged_complaint,
    setup_warranted_intersection,
)

THANKSGIVING = "2026-11-26"


def test_an_absence_filed_for_a_declared_non_school_day_is_refused(api):
    """The holiday sits inside the assignment window, so only the school calendar —
    reached through post and intersection — can reject it, and nothing moves.

    PRD: "and it must not appear in the owning school's `no_school_dates`, since
    there is nothing to cover on a day with no school, or the refusal is
    `ERR_ABSENCE_ON_NON_SCHOOL_DAY` (HTTP 422)."

    Design: Corner/validations/corner_absence_on_declared_non_school_day_rejected
    """
    scenario = setup_staffed_post(start_date="2026-11-23", end_date="2026-11-27",
                                 no_school_dates=[THANKSGIVING])
    assert scenario["school"]["no_school_dates"] == [THANKSGIVING]

    response = api.create_absence_report(
        create_absence_report_payload(scenario["assignment"]["id"],
                                      absence_date=THANKSGIVING,
                                      note="Filed against the holiday by mistake."),
        SUPERVISOR)

    validate_error(response,
                   ApiErrorId.ERR_ABSENCE_ON_NON_SCHOOL_DAY.value, 422)
    assignment = read_assignment(scenario["assignment"]["id"])
    assert assignment["open_absence_count"] == 0
    assert assignment["coverage_state"] == "STAFFED"
    post = read_post(scenario["post"]["id"])
    assert post["open_gap_count"] == 0
    assert post["coverage_status"] == "COVERED"

    accepted = validate_success(api.create_absence_report(
        create_absence_report_payload(scenario["assignment"]["id"],
                                      absence_date="2026-11-25",
                                      note="Genuine duty-day absence."),
        SUPERVISOR), 201)

    assert_absence_report(accepted)
    assert accepted["status"] == "DISPATCH_PENDING"
    assert read_assignment(scenario["assignment"]["id"])["open_absence_count"] == 1
    assert read_post(scenario["post"]["id"])["open_gap_count"] == 1


def test_the_last_day_of_the_assignment_window_can_still_be_missed(api):
    """The window is a closed interval, so its final day is a duty day while the day
    after it is outside the assignment entirely.

    PRD: "The `absence_date` must fall inside the assignment's closed window from
    `start_date` through `end_date` inclusive, or the refusal is
    `ERR_ABSENCE_OUTSIDE_ASSIGNMENT` (HTTP 422)"

    Design: Corner/validations/corner_absence_date_at_assignment_window_edge_accepted
    """
    scenario = setup_staffed_post()
    assignment_id = scenario["assignment"]["id"]
    assert scenario["assignment"]["end_date"] == "2026-09-18"

    outside = api.create_absence_report(
        create_absence_report_payload(assignment_id, absence_date="2026-09-19",
                                      reason="ILLNESS",
                                      note="One day past the window."),
        SUPERVISOR)
    validate_error(outside, ApiErrorId.ERR_ABSENCE_OUTSIDE_ASSIGNMENT.value, 422)

    edge = validate_success(api.create_absence_report(
        create_absence_report_payload(assignment_id, absence_date="2026-09-18",
                                      reason="ILLNESS",
                                      note="Final duty day of the window."),
        SUPERVISOR), 201)

    assert_absence_report(edge)
    assert edge["absence_date"] == "2026-09-18"
    assert edge["status"] == "DISPATCH_PENDING"
    assert edge["shift"] == "AM"
    assert edge["guard_id"] == scenario["guard"]["id"]
    rows, meta = validate_paginated(api.list_absence_reports(
        SUPERVISOR, {"post_assignment_id": assignment_id}))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [edge["id"]]


def test_the_duplicate_gate_releases_once_the_first_report_is_rescinded(api):
    """Uniqueness is scoped to non-terminal reports, so the identical filing that was
    a duplicate becomes legal the moment the incumbent leaves the live set.

    PRD: "At most one **non-terminal** report — one whose `status` is neither
    `COVERED` nor `RESCINDED` — may exist for any given pairing of
    `post_assignment_id` and `absence_date`; a second live report for the same duty
    day is refused with `ERR_ABSENCE_DUPLICATE` (HTTP 409)."

    Design: Corner/validations/corner_absence_duplicate_gate_ignores_terminal_reports
    """
    scenario = setup_staffed_post()
    assignment_id = scenario["assignment"]["id"]
    first = validate_success(api.create_absence_report(
        create_absence_report_payload(assignment_id, absence_date="2026-09-16"),
        SUPERVISOR), 201)

    duplicate = api.create_absence_report(
        create_absence_report_payload(assignment_id, absence_date="2026-09-16",
                                      reason="FAMILY",
                                      note="Duplicate filing for the same duty day."),
        SUPERVISOR)
    validate_error(duplicate, ApiErrorId.ERR_ABSENCE_DUPLICATE.value, 409)
    assert read_absence(first["id"])["status"] == "DISPATCH_PENDING"
    assert read_assignment(assignment_id)["open_absence_count"] == 1

    rescinded = validate_success(api.rescind_absence_report(
        first["id"],
        rescind_absence_payload(rescind_reason="Guard reported for duty after all."),
        SUPERVISOR))
    assert rescinded["status"] == "RESCINDED"
    assert read_assignment(assignment_id)["open_absence_count"] == 0

    refiled = validate_success(api.create_absence_report(
        create_absence_report_payload(assignment_id, absence_date="2026-09-16",
                                      reason="FAMILY",
                                      note="Re-filed after the rescission."),
        SUPERVISOR), 201)

    assert refiled["status"] == "DISPATCH_PENDING"
    assert refiled["id"] != first["id"]
    assert read_assignment(assignment_id)["open_absence_count"] == 1
    assert read_post(scenario["post"]["id"])["open_gap_count"] == 1


CONDITIONAL_SESSIONS = [
    {"session_date": "2026-09-08", "period": "AM_ARRIVAL", "observed_minutes": 60,
     "child_count": 60, "adult_count": 8, "vehicle_count": 600,
     "adequate_gaps": 50},
    {"session_date": "2026-09-09", "period": "PM_DISMISSAL", "observed_minutes": 60,
     "child_count": 40, "adult_count": 6, "vehicle_count": 400,
     "adequate_gaps": 30},
]


def test_a_conditional_warrant_activates_the_morning_post_only(api):
    """CONDITIONAL clears the warrant gate, so the shift restriction has to be a
    second, separate check — and only the afternoon posts feel it.

    PRD: "A `CONDITIONAL` warrant is not disqualifying by itself, but it permits
    morning coverage only, so a separate check runs immediately after the first one
    clears: at a `CONDITIONAL` intersection the post's `required_shift` must be `AM`,
    and a post declaring `PM` or `BOTH` is refused with
    `ERR_POST_SHIFT_NOT_PERMITTED` (HTTP 422)."

    Design: Corner/validations/corner_conditional_warrant_permits_am_post_only
    """
    scenario = setup_finalized_study(sessions=CONDITIONAL_SESSIONS)
    intersection = read_intersection(scenario["intersection"]["id"])
    assert intersection["warrant_status"] == "CONDITIONAL"
    assert intersection["latest_warrant_score"] == 44.85
    morning = validate_success(api.create_guard_post(
        create_guard_post_payload(intersection["id"]), SUPERVISOR), 201)
    afternoon = validate_success(api.create_guard_post(
        create_guard_post_payload(intersection["id"],
                                  post_label="Maple SE corner",
                                  required_shift="PM"), SUPERVISOR), 201)
    all_day = validate_success(api.create_guard_post(
        create_guard_post_payload(intersection["id"],
                                  post_label="Maple SW corner",
                                  required_shift="BOTH"), SUPERVISOR), 201)

    pm_response = api.activate_guard_post(afternoon["id"], ADMIN)
    both_response = api.activate_guard_post(all_day["id"], ADMIN)
    activated = validate_success(api.activate_guard_post(morning["id"], ADMIN))

    pm_error = validate_error(
        pm_response, ApiErrorId.ERR_POST_SHIFT_NOT_PERMITTED.value, 422)
    assert pm_error["error_id"] != ApiErrorId.ERR_POST_NOT_WARRANTED.value
    validate_error(both_response,
                   ApiErrorId.ERR_POST_SHIFT_NOT_PERMITTED.value, 422)
    assert_guard_post(activated)
    assert activated["status"] == "ACTIVE"
    assert read_post(afternoon["id"])["status"] == "PROPOSED"
    assert read_post(afternoon["id"])["activated_at"] is None
    assert read_post(all_day["id"])["status"] == "PROPOSED"
    assert read_post(all_day["id"])["activated_at"] is None
    school = read_school(scenario["school"]["id"])
    assert_school_coverage_partition(school)
    assert school["active_post_count"] == 1
    assert school["uncovered_post_count"] == 1
    assert school["coverage_rate_pct"] == 0.00
    assert school["coverage_posture"] == "SUSPENDED"


def test_one_sweep_reports_an_activation_and_an_ending_independently(api):
    """A single clock advance both starts one window and finishes another, and the
    two counters in the response body must not be conflated.

    PRD: "Every assignment in `SCHEDULED` whose `start_date` is on or before the new
    clock date moves `SCHEDULED → ACTIVE`; every assignment in `ACTIVE` whose
    `end_date` is strictly earlier than the new clock date moves `ACTIVE → ENDED`"

    Design: Corner/endpoints/corner_clock_sweep_returns_activated_and_ended_counts
    """
    scenario = setup_staffed_post()
    second = add_second_post_and_guard(scenario, required_shift="PM",
                                       start_date="2026-09-19",
                                       end_date="2026-09-25")

    first_sweep = validate_success(api.set_clock("2026-09-10T00:00:00Z", ADMIN))
    assert_clock_response(first_sweep, "2026-09-10T00:00:00Z", activated=1, ended=0)
    assert read_assignment(scenario["assignment"]["id"])["status"] == "ACTIVE"
    assert read_assignment(second["assignment"]["id"])["status"] == "SCHEDULED"

    second_sweep = validate_success(api.set_clock("2026-09-19T00:00:00Z", ADMIN))

    assert_clock_response(second_sweep, "2026-09-19T00:00:00Z", activated=1, ended=1)
    assert read_assignment(scenario["assignment"]["id"])["status"] == "ENDED"
    assert read_assignment(second["assignment"]["id"])["status"] == "ACTIVE"
    assert read_guard(scenario["guard"]["id"])["duty_status"] == "UNASSIGNED"
    assert read_guard(second["guard"]["id"])["duty_status"] == "ASSIGNED"
    assert read_post(scenario["post"]["id"])["coverage_status"] == "UNSTAFFED"
    assert read_post(second["post"]["id"])["coverage_status"] == "COVERED"
    school = read_school(scenario["school"]["id"])
    assert_school_coverage_partition(school)
    assert school["active_post_count"] == 2
    assert school["covered_post_count"] == 1
    assert school["uncovered_post_count"] == 1
    assert school["coverage_rate_pct"] == 50.00
    assert school["coverage_posture"] == "RESTRICTED"


def test_citing_a_complaint_forges_the_link_in_both_directions(api):
    """The create call writes three rows: the project, the complaint it cites and the
    program that will one day pay for it — and the link is queryable in reverse.

    PRD: "On success the cited complaint moves `TRIAGED → REFERRED`, its
    `referred_project_id` back-pointer is set to the new project's identifier, and
    its `version` increments by 1"

    Design: Corner/endpoints/corner_project_creation_links_and_flips_cited_complaint
    """
    scenario = setup_warranted_intersection()
    complaint = setup_triaged_complaint(scenario["intersection"]["id"])
    program = create_grant_program(total_cents=12_000_000)
    assert complaint["status"] == "TRIAGED"
    assert complaint["referred_project_id"] is None

    project = validate_success(api.create_infrastructure_project(
        create_project_payload(program["id"], scenario["intersection"]["id"],
                               requested_cost_cents=3_000_000,
                               students_benefited=500,
                               source_complaint_id=complaint["id"]),
        ENGINEER), 201)

    assert_infrastructure_project(project)
    assert project["status"] == "PROPOSED"
    assert project["source_complaint_id"] == complaint["id"]
    referred = read_complaint(complaint["id"])
    assert referred["status"] == "REFERRED"
    assert referred["referred_project_id"] == project["id"]
    assert referred["version"] == complaint["version"] + 1
    after = read_program(program["id"])
    assert after["version"] == program["version"] + 1
    assert after["committed_cents"] == 0
    assert after["remaining_cents"] == 12_000_000
    rows, meta = validate_paginated(api.list_infrastructure_projects(
        ENGINEER, {"source_complaint_id": complaint["id"]}))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [project["id"]]


def test_the_school_coverage_read_reconciles_with_its_posts(api):
    """Two active posts, one staffed and one never staffed, land the school on exactly
    50.00 — and the strict comparison makes that RESTRICTED rather than SUSPENDED.

    PRD: "`coverage_posture` is then `OPEN` when `uncovered_post_count` is exactly 0;
    otherwise `SUSPENDED` when `coverage_rate_pct` is strictly below 50.00; otherwise
    `RESTRICTED`. A rate of exactly 50.00 is `RESTRICTED`, not `SUSPENDED`."

    Design: Corner/endpoints/corner_school_coverage_read_matches_post_level_truth
    """
    scenario = setup_staffed_post()
    unstaffed = create_active_post(scenario["intersection"]["id"],
                                   post_label="Maple SE corner",
                                   required_shift="PM")

    school = validate_success(api.get_school(scenario["school"]["id"], ADMIN))
    staffed_post = validate_success(api.get_guard_post(scenario["post"]["id"], ADMIN))
    empty_post = validate_success(api.get_guard_post(unstaffed["id"], ADMIN))

    assert_school_coverage_partition(school)
    assert school["active_post_count"] == 2
    assert school["covered_post_count"] == 1
    assert school["uncovered_post_count"] == 1
    assert school["coverage_rate_pct"] == 50.00
    assert school["coverage_posture"] == "RESTRICTED"
    assert school["coverage_posture"] != "SUSPENDED"
    assert_guard_post(staffed_post)
    assert staffed_post["coverage_status"] == "COVERED"
    assert staffed_post["open_gap_count"] == 0
    assert_guard_post(empty_post)
    assert empty_post["coverage_status"] == "UNSTAFFED"
    assert empty_post["open_gap_count"] == 0
    assert (school["covered_post_count"] + school["uncovered_post_count"]
            == school["active_post_count"])
