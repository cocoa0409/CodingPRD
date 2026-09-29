"""Lifecycle entry points, invalid transitions and terminal-state locks.

Each entity in this program has exactly one legal way in and a small set of
legal ways on, and several endpoints are deliberately not idempotent. These
tests pin the birth state of a warrant study, the preconditions the study
lifecycle enforces on its way to a determination, the locks that protect a
terminal row, and the duty-status cycle a guard walks independently of
certification.
"""
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_count_session,
    assert_same_instant,
    assert_guard,
    assert_guard_post,
    assert_school_coverage_partition,
    assert_walking_route,
    assert_warrant_study,
)
from test_helpers.factories import (
    create_count_session_payload,
    create_warrant_study_payload,
    duty_status_payload,
    finalize_study_payload,
    reopen_counting_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    CANONICAL_AM_SESSION,
    ENGINEER,
    SECOND_ENGINEER,
    SUPERVISOR,
    create_intersection,
    create_school,
    dispatch,
    open_warrant_study,
    read_absence,
    read_assignment,
    read_guard,
    read_intersection,
    read_post,
    read_route,
    read_school,
    read_study,
    record_count_session,
    setup_absence_ready_for_dispatch,
    setup_analyzed_study,
    setup_certified_guard,
    setup_published_route,
    setup_staffed_post,
    setup_study_ready_to_analyze,
    setup_warranted_intersection,
)
from test_helpers.test_users import ENGINEER_USER_ID, make_school_liaison_headers

RECOUNT_REASON = "Counter miscalibration on the AM session; recount ordered."
LATE_OBJECTION = "Late objection from the neighborhood association."


def test_opening_a_study_writes_both_the_study_and_its_intersection(api):
    """One call, two entities: the study is born empty and the parent intersection
    leaves NOT_STUDIED in the same breath.

    PRD: "A study is born in `DRAFT`, with an empty `count_sessions` array,
    `recount_round` at 0, `authored_by_user_id` set to the creating engineer's
    `X-User-ID`" ... "Creation immediately pushes the parent intersection's
    `warrant_status` to `UNDER_STUDY` and increments the intersection's `version`
    by 1."

    Design: Corner/state_machines/corner_new_study_starts_draft_and_flips_intersection_to_under_study
    """
    school = create_school()
    intersection = create_intersection(school["id"])
    assert intersection["warrant_status"] == "NOT_STUDIED"
    assert intersection["latest_warrant_score"] is None

    study = validate_success(api.create_warrant_study(
        create_warrant_study_payload(intersection["id"],
                                     intersection["version"]), ENGINEER), 201)

    assert_warrant_study(study)
    assert study["status"] == "DRAFT"
    assert study["count_sessions"] == []
    assert study["recount_round"] == 0
    assert study["warrant_score"] is None
    assert study["determination"] is None
    assert study["scoring_variant"] is None
    assert study["reopen_reason"] is None
    assert study["authored_by_user_id"] == ENGINEER_USER_ID
    assert study["finalized_by_user_id"] is None
    after = read_intersection(intersection["id"])
    assert after["warrant_status"] == "UNDER_STUDY"
    assert after["latest_warrant_score"] is None
    assert after["version"] == intersection["version"] + 1


def test_a_study_with_only_a_morning_session_cannot_be_analyzed(api):
    """Two morning sessions would clear the count test but not the coverage test;
    one morning session clears neither, and no scoring work is done.

    PRD: "there must be at least two non-voided sessions whose `period` is
    `AM_ARRIVAL` or `PM_DISMISSAL`, **and at least one of each of those two
    periods**."

    Design: Corner/state_machines/corner_analyze_rejected_without_both_count_periods
    """
    scenario = setup_study_ready_to_analyze(sessions=[CANONICAL_AM_SESSION])
    assert scenario["study"]["status"] == "COUNTING"
    assert len(scenario["study"]["count_sessions"]) == 1

    response = api.analyze_warrant_study(scenario["study"]["id"], ENGINEER)

    validate_error(response,
                   ApiErrorId.ERR_INSUFFICIENT_COUNT_COVERAGE.value, 422)
    study = read_study(scenario["study"]["id"])
    assert study["status"] == "COUNTING"
    assert study["status"] != "ANALYZED"
    assert study["warrant_score"] is None
    assert study["determination"] is None
    assert study["scoring_variant"] is None
    assert read_intersection(scenario["intersection"]["id"])["warrant_status"] == "UNDER_STUDY"


def test_reopening_an_analyzed_study_voids_its_sessions_without_deleting_them(api):
    """Five writes and one deliberate non-write: the sessions survive as voided
    history while every computed aggregate returns to null.

    PRD: "`voided` is flipped to true on every existing entry of `count_sessions`
    with no entry deleted" ... "`recount_round` increments by 1 and the supplied
    `reopen_reason` is stored; the parent intersection returns to `UNDER_STUDY`
    with `latest_warrant_score` cleared to null and its `version` incremented by 1"

    Design: Corner/state_machines/corner_reopen_counting_voids_sessions_and_clears_aggregates
    """
    scenario = setup_analyzed_study()
    assert scenario["study"]["warrant_score"] == 66.19
    assert scenario["study"]["determination"] == "WARRANTED"

    reopened = validate_success(api.reopen_counting(
        scenario["study"]["id"],
        reopen_counting_payload(reopen_reason=RECOUNT_REASON), ENGINEER))

    assert_warrant_study(reopened)
    assert reopened["status"] == "COUNTING"
    assert reopened["recount_round"] == 1
    assert reopened["reopen_reason"] == RECOUNT_REASON
    assert len(reopened["count_sessions"]) == 2
    for session in reopened["count_sessions"]:
        assert_count_session(session)
        assert session["voided"] is True
    assert reopened["warrant_score"] is None
    assert reopened["determination"] is None
    assert reopened["scoring_variant"] is None
    assert reopened["included_child_count"] is None
    assert reopened["included_adequate_gaps"] is None
    assert reopened["included_vehicle_count"] is None
    assert reopened["pedestrian_crash_count_3yr"] is None
    assert reopened["severe_pedestrian_crash_count_3yr"] is None
    intersection = read_intersection(scenario["intersection"]["id"])
    assert intersection["warrant_status"] == "UNDER_STUDY"
    assert intersection["latest_warrant_score"] is None


def test_a_warranted_study_is_terminal_and_refuses_reopening(api):
    """WARRANTED is the one terminal status of the study lifecycle, and the refusal
    leaves both the study and the adopted determination alone.

    PRD: "A `TrafficEngineer` may reopen a study whose `status` is `ANALYZED`,
    `CONDITIONAL` or `NOT_WARRANTED`, supplying a mandatory free-text
    `reopen_reason`; a `WARRANTED` study is terminal and any other status is
    refused with `ERR_STUDY_NOT_REOPENABLE` (HTTP 409)."

    Design: Corner/state_machines/corner_warranted_study_is_locked_against_reopening
    """
    scenario = setup_warranted_intersection()
    before = read_study(scenario["study"]["id"])
    assert before["status"] == "WARRANTED"

    response = api.reopen_counting(
        before["id"], reopen_counting_payload(reopen_reason=LATE_OBJECTION),
        ENGINEER)

    validate_error(response, ApiErrorId.ERR_STUDY_NOT_REOPENABLE.value, 409)
    study = read_study(before["id"])
    assert study["status"] == "WARRANTED"
    assert study["recount_round"] == 0
    assert study["reopen_reason"] is None
    assert study["version"] == before["version"]
    for session in study["count_sessions"]:
        assert session["voided"] is False
    intersection = read_intersection(scenario["intersection"]["id"])
    assert intersection["warrant_status"] == "WARRANTED"
    assert intersection["latest_warrant_score"] == 66.19


def test_a_further_count_session_is_refused_once_the_study_is_analyzed(api):
    """Recording is legal from DRAFT or COUNTING only, so an ANALYZED study cannot
    have its computed score quietly invalidated by a late session.

    PRD: "Recording is permitted only while the study's `status` is `DRAFT` or
    `COUNTING`; anywhere else the request is refused with
    `ERR_STUDY_NOT_IN_COUNTING` (HTTP 409)."

    Design: Corner/state_machines/corner_count_session_rejected_after_analyze
    """
    scenario = setup_analyzed_study()
    before = read_study(scenario["study"]["id"])
    assert before["status"] == "ANALYZED"

    response = api.create_count_session(
        before["id"],
        create_count_session_payload(session_date="2026-09-10",
                                     child_count=90, adult_count=12,
                                     vehicle_count=600, adequate_gaps=10),
        ENGINEER)

    validate_error(response, ApiErrorId.ERR_STUDY_NOT_IN_COUNTING.value, 409)
    study = read_study(before["id"])
    assert study["status"] == "ANALYZED"
    assert len(study["count_sessions"]) == 2
    assert study["warrant_score"] == 66.19
    assert study["determination"] == "WARRANTED"
    assert study["included_child_count"] == 120
    assert study["version"] == before["version"]


def test_publishing_a_published_route_a_second_time_is_refused(api):
    """Publication is not idempotent: the second call neither re-stamps
    `published_at` nor retires the route against itself.

    PRD: "Publication, again by a `SchoolLiaison` or a `ProgramAdmin`, requires the
    route to be in `DRAFT`; anything else is refused with `ERR_ROUTE_NOT_DRAFT`
    (HTTP 409)."

    Design: Corner/state_machines/corner_second_publish_on_published_route_rejected
    """
    school = create_school()
    route = setup_published_route(school["id"])
    assert route["status"] == "PUBLISHED"
    assert route["hazard_score"] == 1.66
    assert_same_instant(route["published_at"], "2026-08-01T00:00:00Z",
                        "WalkingRoute.published_at")

    response = api.publish_walking_route(
        route["id"], make_school_liaison_headers(school["id"]))

    validate_error(response, ApiErrorId.ERR_ROUTE_NOT_DRAFT.value, 409)
    after = read_route(route["id"])
    assert_walking_route(after)
    assert after["status"] == "PUBLISHED"
    assert after["hold_reason"] is None
    assert after["version"] == route["version"]
    assert after["published_at"] == route["published_at"]
    routes, meta = validate_paginated(
        api.list_school_walking_routes(school["id"], ADMIN))
    assert meta["total_count"] == 1
    assert [row["status"] for row in routes] == ["PUBLISHED"]


def test_a_second_dispatch_over_a_live_offer_is_refused(api):
    """Re-dispatching is a retry over a lapsed offer, so with the clock inside the
    45-minute window the report must not advance in any way.

    PRD: "A report in `OFFER_OUT` whose offer is still live, or one already
    terminal, is refused with `ERR_ABSENCE_NOT_DISPATCHABLE`"

    Design: Corner/state_machines/corner_second_dispatch_while_offer_open_rejected
    """
    scenario = setup_absence_ready_for_dispatch()
    sam = scenario["substitutes"][0]
    offered = dispatch(scenario["absence"]["id"])
    assert offered["status"] == "OFFER_OUT"
    assert_same_instant(offered["current_offer_expires_at"], "2026-09-16T01:45:00Z",
                        "AbsenceReport.current_offer_expires_at")

    response = api.dispatch_absence_report(scenario["absence"]["id"], SUPERVISOR)

    validate_error(response, ApiErrorId.ERR_ABSENCE_NOT_DISPATCHABLE.value, 409)
    report = read_absence(scenario["absence"]["id"])
    assert report["status"] == "OFFER_OUT"
    assert report["dispatch_attempt_count"] == 1
    assert len(report["dispatch_offers"]) == 1
    assert report["dispatch_offers"][0]["offer_status"] == "OPEN"
    assert_same_instant(report["dispatch_offers"][0]["offer_expires_at"],
                        "2026-09-16T01:45:00Z", "DispatchOffer.offer_expires_at")
    assert report["current_offer_guard_id"] == sam["id"]
    assert report["excluded_guard_ids"] == []
    assert report["version"] == offered["version"]


def test_the_duty_status_cycle_refuses_to_be_driven_past_its_own_edges(api):
    """UNASSIGNED to ON_LEAVE and back is a clean round trip, but each edge is
    guarded by the current state and certification never moves with it.

    PRD: "`RETURN` is accepted only from `ON_LEAVE`, and its destination is a fork
    decided by the guard's assignment set rather than by anything in the request
    body: a guard still holding at least one assignment in `SCHEDULED` or `ACTIVE`
    returns to `ASSIGNED`, while a guard holding none returns to `UNASSIGNED`.
    Asking for `ON_LEAVE` on a guard already `ON_LEAVE`, or `RETURN` on a guard who
    is not `ON_LEAVE`, is refused with `ERR_INVALID_DUTY_ACTION` (HTTP 422)."

    Design: Corner/state_machines/corner_duty_status_cycle_rejects_repeated_action
    """
    guard = setup_certified_guard()
    assert guard["duty_status"] == "UNASSIGNED"

    on_leave = validate_success(api.set_duty_status(
        guard["id"], duty_status_payload("ON_LEAVE"), SUPERVISOR))
    assert_guard(on_leave)
    assert on_leave["duty_status"] == "ON_LEAVE"

    repeated = api.set_duty_status(guard["id"], duty_status_payload("ON_LEAVE"),
                                  SUPERVISOR)
    validate_error(repeated, ApiErrorId.ERR_INVALID_DUTY_ACTION.value, 422)
    assert read_guard(guard["id"])["duty_status"] == "ON_LEAVE"

    returned = validate_success(api.set_duty_status(
        guard["id"], duty_status_payload("RETURN"), SUPERVISOR))
    assert returned["duty_status"] == "UNASSIGNED"
    assert returned["duty_status"] != "ASSIGNED"

    again = api.set_duty_status(guard["id"], duty_status_payload("RETURN"),
                               SUPERVISOR)
    validate_error(again, ApiErrorId.ERR_INVALID_DUTY_ACTION.value, 422)
    final = read_guard(guard["id"])
    assert final["duty_status"] == "UNASSIGNED"
    assert final["certification_status"] == "CERTIFIED"


def test_adopting_a_negative_determination_suspends_the_post_and_frees_the_guard(api):
    """The cascade runs down two levels and then the school recomputation lands on
    its counter-intuitive resting point: no active posts means a full rate and an
    OPEN posture, so the published route is left alone.

    PRD: "**every** `ACTIVE` guard post at the intersection moves `ACTIVE →
    SUSPENDED` with `suspension_reason` set to `WARRANT_LAPSED`, regardless of
    `required_shift`." ... "A school with no active posts is `OPEN` with a rate of
    100.00."

    Design: Corner/state_machines/corner_not_warranted_finalize_suspends_post_and_vacates_assignment
    """
    scenario = setup_staffed_post()
    route = setup_published_route(scenario["school"]["id"])
    intersection = read_intersection(scenario["intersection"]["id"])
    recount = open_warrant_study(intersection["id"], intersection["version"],
                                count_window_start="2026-11-02",
                                count_window_end="2026-11-20")
    record_count_session(recount["id"],
                         {"session_date": "2026-11-02", "period": "AM_ARRIVAL",
                          "observed_minutes": 60, "child_count": 12,
                          "adult_count": 4, "vehicle_count": 120,
                          "adequate_gaps": 40})
    record_count_session(recount["id"],
                         {"session_date": "2026-11-03", "period": "PM_DISMISSAL",
                          "observed_minutes": 60, "child_count": 8,
                          "adult_count": 2, "vehicle_count": 80,
                          "adequate_gaps": 30})
    analyzed = validate_success(api.analyze_warrant_study(recount["id"], ENGINEER))
    assert analyzed["warrant_score"] == 17.71
    assert analyzed["determination"] == "NOT_WARRANTED"

    adopted = validate_success(api.finalize_warrant_study(
        recount["id"], SECOND_ENGINEER,
        finalize_study_payload(
            engineer_note="Counts no longer support a guarded crossing.")))

    assert adopted["status"] == "NOT_WARRANTED"
    assert adopted["warrant_score"] == 17.71
    after = read_intersection(intersection["id"])
    assert after["warrant_status"] == "NOT_WARRANTED"
    assert after["latest_warrant_score"] == 17.71
    post = read_post(scenario["post"]["id"])
    assert_guard_post(post)
    assert post["status"] == "SUSPENDED"
    assert post["suspension_reason"] == "WARRANT_LAPSED"
    assert post["coverage_status"] == "UNSTAFFED"
    assignment = read_assignment(scenario["assignment"]["id"])
    assert assignment["status"] == "VACATED"
    assert assignment["vacated_reason"] == "POST_SUSPENDED"
    assert read_guard(scenario["guard"]["id"])["duty_status"] == "UNASSIGNED"
    school = read_school(scenario["school"]["id"])
    assert_school_coverage_partition(school)
    assert school["active_post_count"] == 0
    assert school["covered_post_count"] == 0
    assert school["uncovered_post_count"] == 0
    assert school["coverage_rate_pct"] == 100.00
    assert school["coverage_posture"] == "OPEN"
    held = read_route(route["id"])
    assert held["status"] == "PUBLISHED"
    assert held["hold_reason"] is None
    assert read_study(scenario["study"]["id"])["status"] == "WARRANTED"
