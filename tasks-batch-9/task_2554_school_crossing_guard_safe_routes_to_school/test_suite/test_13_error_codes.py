"""Which error code each refusal reports, and the order the checks run in.

An error catalogue is only useful if every entry is distinguishable from its
neighbours: a shared 404, or a state error reported where a threshold error
belongs, would let a client mistake one situation for another. These tests drive
the same fixture into adjacent failure modes and pin the code, the HTTP status
and — where the PRD fixes an order — which of two live violations answers first.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_clock_response,
    assert_same_instant,
    assert_grant_program,
    assert_guard,
    assert_infrastructure_project,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.factories import (
    certify_guard_payload,
    create_absence_report_payload,
    create_assignment_payload,
    create_count_session_payload,
    create_guard_post_payload,
    create_project_payload,
    duty_status_payload,
    fund_project_payload,
    offer_response_payload,
    rescind_absence_payload,
    triage_complaint_payload,
    withdraw_funding_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    CANONICAL_AM_SESSION,
    CANONICAL_PM_SESSION,
    ENGINEER,
    SECOND_ENGINEER,
    SUPERVISOR,
    advance_clock,
    create_active_post,
    create_grant_program,
    create_guard,
    create_intersection,
    create_school,
    dispatch,
    file_absence,
    issue_full_equipment,
    propose_project,
    read_absence,
    read_assignment,
    read_complaint,
    read_guard,
    read_intersection,
    read_post,
    read_program,
    read_project,
    read_study,
    record_count_session,
    record_training,
    rescind,
    setup_absence_ready_for_dispatch,
    setup_certified_guard,
    setup_scored_project,
    setup_staffed_post,
    setup_study_ready_to_analyze,
    setup_triaged_complaint,
    setup_warranted_intersection,
)
from test_helpers.test_users import ENGINEER_USER_ID, make_crossing_guard_headers


def test_each_path_prefix_reports_its_own_not_found_code(api):
    """Ten reads against well-formed but unknown identifiers must produce ten
    different error ids, and a real read afterwards proves the probes were not
    simply a blanket failure.

    PRD: "Path identifiers are resolved strictly left to right, and the first
    segment that fails to resolve decides the error." ... "A school path segment
    that resolves to nothing yields `ERR_SCHOOL_NOT_FOUND`" ... "All of these are
    HTTP 404."

    Design: Corner/errors/corner_every_path_resource_reports_its_own_not_found_code
    """
    school = create_school()
    probes = [
        (api.get_school(NON_EXISTENT_UUID, ADMIN),
         ApiErrorId.ERR_SCHOOL_NOT_FOUND),
        (api.get_warrant_study(NON_EXISTENT_UUID, ENGINEER),
         ApiErrorId.ERR_WARRANT_STUDY_NOT_FOUND),
        (api.get_guard(NON_EXISTENT_UUID, SUPERVISOR),
         ApiErrorId.ERR_GUARD_NOT_FOUND),
        (api.get_guard_post(NON_EXISTENT_UUID, ADMIN),
         ApiErrorId.ERR_GUARD_POST_NOT_FOUND),
        (api.get_post_assignment(NON_EXISTENT_UUID, SUPERVISOR),
         ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
        (api.get_absence_report(NON_EXISTENT_UUID, SUPERVISOR),
         ApiErrorId.ERR_ABSENCE_NOT_FOUND),
        (api.get_walking_route(NON_EXISTENT_UUID, ADMIN),
         ApiErrorId.ERR_ROUTE_NOT_FOUND),
        (api.get_complaint(NON_EXISTENT_UUID, ENGINEER),
         ApiErrorId.ERR_COMPLAINT_NOT_FOUND),
        (api.get_grant_program(NON_EXISTENT_UUID, ADMIN),
         ApiErrorId.ERR_GRANT_PROGRAM_NOT_FOUND),
        (api.get_infrastructure_project(NON_EXISTENT_UUID, ENGINEER),
         ApiErrorId.ERR_PROJECT_NOT_FOUND),
    ]

    reported = []
    for response, expected in probes:
        reported.append(validate_error(response, expected.value, 404)["error_id"])

    assert len(reported) == 10
    assert len(set(reported)) == 10
    survivor = validate_success(api.get_school(school["id"], ADMIN))
    assert survivor["id"] == school["id"]


def test_the_first_declared_body_foreign_key_decides_the_error(api):
    """Three unknown foreign keys in one project payload, and the code names the
    first field the endpoint declares; on the staffing path an unknown guard is a
    404 rather than one of the 422 eligibility refusals.

    PRD: "Foreign keys carried in the request body are resolved only after every
    path identifier has resolved, and among themselves they are checked in the
    order the endpoint declares its input fields." ... "`guard_id` yields
    `ERR_GUARD_NOT_FOUND`; `post_assignment_id` yields `ERR_ASSIGNMENT_NOT_FOUND`;
    `grant_program_id` yields `ERR_GRANT_PROGRAM_NOT_FOUND`"

    Design: Corner/errors/corner_body_foreign_keys_resolve_in_declared_field_order
    """
    scenario = setup_warranted_intersection()
    post = create_active_post(scenario["intersection"]["id"])
    post_version = post["version"]

    all_unknown = api.create_infrastructure_project(
        create_project_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                               scope_summary="All three foreign keys are unknown.",
                               requested_cost_cents=3_000_000,
                               students_benefited=500,
                               source_complaint_id=NON_EXISTENT_UUID),
        ENGINEER)
    unknown_guard = api.create_assignment(
        post["id"], create_assignment_payload(NON_EXISTENT_UUID, post_version),
        SUPERVISOR)
    unknown_assignment = api.create_absence_report(
        create_absence_report_payload(NON_EXISTENT_UUID), SUPERVISOR)

    program_error = validate_error(
        all_unknown, ApiErrorId.ERR_GRANT_PROGRAM_NOT_FOUND.value, 404)
    assert program_error["error_id"] != ApiErrorId.ERR_INTERSECTION_NOT_FOUND.value
    assert program_error["error_id"] != ApiErrorId.ERR_COMPLAINT_NOT_FOUND.value
    guard_error = validate_error(
        unknown_guard, ApiErrorId.ERR_GUARD_NOT_FOUND.value, 404)
    assert guard_error["error_id"] != ApiErrorId.ERR_GUARD_NOT_CERTIFIED.value
    validate_error(unknown_assignment,
                   ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND.value, 404)
    untouched = read_post(post["id"])
    assert untouched["coverage_status"] == "UNSTAFFED"
    assert untouched["version"] == post_version


LATE_SESSION = {
    "session_date": "2026-10-01",
    "period": "PM_DISMISSAL",
    "observed_minutes": 60,
    "child_count": 50,
    "adult_count": 8,
    "vehicle_count": 380,
    "adequate_gaps": 20,
}


def test_the_study_path_separates_state_window_and_duty_refusals(api):
    """One study reaches three distinct codes: too early to adopt, a session dated
    one day past the closed window, and finally the author trying to adopt his own
    determination — a 403 that survives a passing role check.

    PRD: "Adoption requires the study to be in `ANALYZED`; from any other status
    the refusal is `ERR_STUDY_NOT_ANALYZED` (HTTP 409)." ... "The `session_date`
    must fall inside the study's closed observation window, from
    `count_window_start` through `count_window_end` inclusive; outside it, the
    rejection is `ERR_SESSION_DATE_OUTSIDE_WINDOW` (HTTP 422)." ... "an
    `X-User-ID` equal to the study's `authored_by_user_id` is refused with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/errors/corner_study_lifecycle_error_codes
    """
    scenario = setup_study_ready_to_analyze(sessions=[CANONICAL_AM_SESSION])
    study_id = scenario["study"]["id"]
    assert scenario["study"]["status"] == "COUNTING"

    premature = api.finalize_warrant_study(
        study_id, SECOND_ENGINEER, {"engineer_note": "Premature adoption attempt."})
    validate_error(premature, ApiErrorId.ERR_STUDY_NOT_ANALYZED.value, 409)
    assert read_study(study_id)["status"] == "COUNTING"

    outside_window = api.create_count_session(
        study_id, create_count_session_payload(**LATE_SESSION), ENGINEER)
    validate_error(outside_window,
                   ApiErrorId.ERR_SESSION_DATE_OUTSIDE_WINDOW.value, 422)
    assert len(read_study(study_id)["count_sessions"]) == 1

    record_count_session(study_id, CANONICAL_PM_SESSION)
    analyzed = validate_success(api.analyze_warrant_study(study_id, ENGINEER))
    assert analyzed["status"] == "ANALYZED"
    assert analyzed["warrant_score"] == 66.19

    self_adoption = api.finalize_warrant_study(
        study_id, ENGINEER, {"engineer_note": "Self-finalizing my own study."})

    validate_error(self_adoption,
                   ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    blocked = read_study(study_id)
    assert blocked["status"] == "ANALYZED"
    assert blocked["finalized_by_user_id"] is None
    assert blocked["authored_by_user_id"] == ENGINEER_USER_ID
    intersection = read_intersection(scenario["intersection"]["id"])
    assert intersection["warrant_status"] == "UNDER_STUDY"
    assert intersection["latest_warrant_score"] is None


def test_the_certify_endpoint_separates_a_state_refusal_from_a_threshold_one(api):
    """An applicant with no training is refused on state; the same guard with 8 of
    the required 12 hours is refused on the threshold; and once certified, the
    refresher counter resets so an immediate recertification hits the same
    threshold code through a different clause.

    PRD: "A guard still in `APPLICANT` has no training on record and is refused
    with `ERR_GUARD_NOT_IN_TRAINING` (HTTP 409); the operation is available only
    from `IN_TRAINING`, `CERTIFIED` or `SUSPENDED`." ... "From `CERTIFIED` it is
    **recertification**, a self-loop that requires `hours_since_last_certification`
    of at least 4.0" ... "Either shortfall is refused with
    `ERR_TRAINING_HOURS_INSUFFICIENT` (HTTP 422)."

    Design: Corner/errors/corner_certification_gate_error_codes
    """
    guard = create_guard(full_name="Priya Raman")
    issue_full_equipment(guard["id"])
    assert read_guard(guard["id"])["certification_status"] == "APPLICANT"

    untrained = api.certify_guard(guard["id"], certify_guard_payload(), SUPERVISOR)
    validate_error(untrained, ApiErrorId.ERR_GUARD_NOT_IN_TRAINING.value, 409)
    assert read_guard(guard["id"])["certification_status"] == "APPLICANT"

    partial = record_training(guard["id"], hours=8.0)
    assert partial["certification_status"] == "IN_TRAINING"
    assert partial["training_hours_completed"] == 8
    short = api.certify_guard(guard["id"], certify_guard_payload(), SUPERVISOR)
    validate_error(short, ApiErrorId.ERR_TRAINING_HOURS_INSUFFICIENT.value, 422)
    assert read_guard(guard["id"])["certification_status"] == "IN_TRAINING"

    topped_up = record_training(guard["id"], hours=4.0, training_date="2026-08-06")
    assert topped_up["training_hours_completed"] == 12
    assert topped_up["hours_since_last_certification"] == 12

    certified = validate_success(api.certify_guard(
        guard["id"], certify_guard_payload(), SUPERVISOR))
    assert_guard(certified)
    assert certified["certification_status"] == "CERTIFIED"
    assert certified["certified_on"] == "2026-08-07"
    assert certified["hours_since_last_certification"] == 0

    recertify = api.certify_guard(
        guard["id"], certify_guard_payload(certified_on="2026-08-08"), SUPERVISOR)

    validate_error(recertify,
                   ApiErrorId.ERR_TRAINING_HOURS_INSUFFICIENT.value, 422)
    unchanged = read_guard(guard["id"])
    assert unchanged["certification_status"] == "CERTIFIED"
    assert unchanged["certified_on"] == "2026-08-07"
    assert unchanged["certification_expires_on"] == "2027-06-30"
    assert unchanged["hours_since_last_certification"] == 0


UNEXCUSED_DATES = ["2026-09-09", "2026-09-10", "2026-09-11"]


def test_a_guard_under_the_reliability_floor_cannot_be_reinstated(api):
    """Three no-shows walk the rolling score down 93.00, 83.00, 73.00; the third
    crosses the floor and suspends the guard, and the reinstatement attempt is
    refused on reliability rather than on training hours.

    PRD: "When a newly created absence report drops
    `reliability_score_rolling_90d` **strictly below 75.00** for a guard whose
    `certification_status` is `CERTIFIED`, that guard moves `CERTIFIED →
    SUSPENDED` with `suspension_reason` set to `RELIABILITY_BREACH`" ... "From
    `SUSPENDED` it is **reinstatement**, which requires
    `reliability_score_rolling_90d` of at least 75.00 evaluated against the
    current logical clock; below that floor the refusal is
    `ERR_RELIABILITY_TOO_LOW` (HTTP 422)"

    Design: Corner/errors/corner_reliability_floor_blocks_reinstatement
    """
    scenario = setup_staffed_post()
    assignment_id = scenario["assignment"]["id"]
    guard_id = scenario["guard"]["id"]
    assert scenario["guard"]["training_hours_completed"] == 12

    expected_rolling = [93.00, 83.00, 73.00]
    for absence_date, expected in zip(UNEXCUSED_DATES, expected_rolling):
        file_absence(assignment_id, absence_date=absence_date,
                     reason="UNEXCUSED", note="No call, no show.")
        charged = read_guard(guard_id)
        assert charged["reliability_score_rolling_90d"] == expected

    suspended = read_guard(guard_id)
    assert_guard(suspended)
    assert suspended["reliability_score_season_to_date"] == 73.00
    assert suspended["certification_status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "RELIABILITY_BREACH"
    assert suspended["duty_status"] == "UNASSIGNED"
    vacated = read_assignment(assignment_id)
    assert vacated["status"] == "VACATED"
    assert vacated["vacated_reason"] == "GUARD_SUSPENDED"

    reinstatement = api.certify_guard(
        guard_id, certify_guard_payload(certified_on="2026-08-08"), SUPERVISOR)

    error = validate_error(reinstatement,
                           ApiErrorId.ERR_RELIABILITY_TOO_LOW.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_TRAINING_HOURS_INSUFFICIENT.value
    still_suspended = read_guard(guard_id)
    assert still_suspended["certification_status"] == "SUSPENDED"
    assert still_suspended["suspension_reason"] == "RELIABILITY_BREACH"


def test_the_two_post_state_codes_are_not_interchangeable(api):
    """Activating an already-active post and staffing a still-proposed one are
    adjacent 409s that must report different codes, and the second call carries a
    perfectly fresh version token so the state check is what answers.

    PRD: "The post must currently be in `PROPOSED` or `SUSPENDED`, since
    activating an already-`ACTIVE` post is refused with `ERR_POST_NOT_ACTIVATABLE`
    (HTTP 409)" ... "The post must be in `ACTIVE`, or the request is refused with
    `ERR_POST_NOT_ACTIVE` (HTTP 409); the stale-version guard is evaluated
    immediately after that state check."

    Design: Corner/errors/corner_post_and_assignment_state_error_codes
    """
    scenario = setup_warranted_intersection()
    active = create_active_post(scenario["intersection"]["id"])
    proposed = validate_success(api.create_guard_post(
        create_guard_post_payload(scenario["intersection"]["id"],
                                  post_label="Maple SE corner"),
        SUPERVISOR), 201)
    guard = setup_certified_guard()
    active_version = active["version"]
    assert_same_instant(active["activated_at"], CLOCK_EPOCH,
                        "GuardPost.activated_at")
    assert proposed["status"] == "PROPOSED"

    reactivation = api.activate_guard_post(active["id"], ADMIN)
    on_proposed_post = api.create_assignment(
        proposed["id"],
        create_assignment_payload(guard["id"], proposed["version"]),
        SUPERVISOR)

    validate_error(reactivation, ApiErrorId.ERR_POST_NOT_ACTIVATABLE.value, 409)
    unmoved = read_post(active["id"])
    assert unmoved["status"] == "ACTIVE"
    assert unmoved["version"] == active_version
    assert_same_instant(unmoved["activated_at"], CLOCK_EPOCH,
                        "GuardPost.activated_at")
    error = validate_error(on_proposed_post,
                           ApiErrorId.ERR_POST_NOT_ACTIVE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_STALE_GUARD_POST_VERSION.value
    rows, meta = validate_paginated(api.list_post_assignments(
        SUPERVISOR, {"guard_post_id": proposed["id"]}))
    assert rows == []
    assert meta["total_count"] == 0
    assert read_post(proposed["id"])["status"] == "PROPOSED"
    assert read_guard(guard["id"])["duty_status"] == "UNASSIGNED"


def test_leave_and_the_season_boundary_are_distinct_staffing_refusals(api):
    """A fully equipped, currently certified guard is still refused while she is on
    leave; returning her to duty clears that, and the window that then straddles
    the last day of the session is refused on the season rather than on her
    certification, which runs well past it.

    PRD: "And the guard's `duty_status` must not be `ON_LEAVE`, or the refusal is
    `ERR_GUARD_ON_LEAVE`." ... "the whole window must lie inside the school's
    instructional session, meaning `start_date` on or after `session_start_date`
    and `end_date` on or before `session_end_date`, with the school resolved from
    the post through its intersection; a window poking outside the session is
    refused with `ERR_ASSIGNMENT_OUTSIDE_SESSION` (HTTP 422)."

    Design: Corner/errors/corner_assignment_eligibility_error_codes
    """
    scenario = setup_warranted_intersection()
    assert scenario["school"]["session_end_date"] == "2027-06-11"
    post = create_active_post(scenario["intersection"]["id"])
    post_version = post["version"]
    guard = setup_certified_guard()
    on_leave = validate_success(api.set_duty_status(
        guard["id"], duty_status_payload("ON_LEAVE"), SUPERVISOR))
    assert on_leave["duty_status"] == "ON_LEAVE"
    assert on_leave["certification_status"] == "CERTIFIED"
    assert on_leave["equipment_complete"] is True

    while_away = api.create_assignment(
        post["id"], create_assignment_payload(guard["id"], post_version),
        SUPERVISOR)
    leave_error = validate_error(while_away,
                                ApiErrorId.ERR_GUARD_ON_LEAVE.value, 422)
    assert leave_error["error_id"] != ApiErrorId.ERR_GUARD_NOT_CERTIFIED.value

    returned = validate_success(api.set_duty_status(
        guard["id"], duty_status_payload("RETURN"), SUPERVISOR))
    assert returned["duty_status"] == "UNASSIGNED"
    assert returned["certification_expires_on"] == "2027-06-30"

    past_the_season = api.create_assignment(
        post["id"],
        create_assignment_payload(guard["id"], post_version,
                                  start_date="2027-06-08",
                                  end_date="2027-06-15"),
        SUPERVISOR)

    season_error = validate_error(
        past_the_season, ApiErrorId.ERR_ASSIGNMENT_OUTSIDE_SESSION.value, 422)
    assert season_error["error_id"] != ApiErrorId.ERR_GUARD_CERT_EXPIRED.value
    unstaffed = read_post(post["id"])
    assert unstaffed["coverage_status"] == "UNSTAFFED"
    assert unstaffed["version"] == post_version
    rows, meta = validate_paginated(api.list_post_assignments(
        SUPERVISOR, {"guard_post_id": post["id"]}))
    assert rows == []
    assert meta["total_count"] == 0


def test_the_three_offer_response_refusals_run_in_a_fixed_order(api):
    """A stranger answering a live offer, the recipient answering a report with no
    offer on it, and the recipient answering one minute too late are three
    different refusals — and the state check outranks the identity check, which in
    turn outranks expiry.

    PRD: "The report must be in `OFFER_OUT`, or the refusal is `ERR_NO_OPEN_OFFER`
    (HTTP 409). The acting `X-User-ID` must equal `current_offer_guard_id`, or the
    refusal is `ERR_NOT_OFFER_RECIPIENT` (HTTP 403). Only then is expiry checked:
    the logical clock must be at or before `current_offer_expires_at`, or the
    refusal is `ERR_OFFER_EXPIRED` (HTTP 409)." ... "When the dispatch is a
    re-offer over a lapsed offer, the lapsed entry's `offer_status` is first
    rewritten from `OPEN` to `EXPIRED`"

    Design: Corner/errors/corner_offer_response_error_codes
    """
    scenario = setup_absence_ready_for_dispatch(
        substitutes=[("Nia Brandt", "Z-SOUTH"), ("Sam Okafor", "Z-NORTH")])
    nia, sam = scenario["substitutes"]
    absence_id = scenario["absence"]["id"]
    never_dispatched = file_absence(scenario["assignment"]["id"],
                                    absence_date="2026-09-17",
                                    note="Second duty day at risk.")
    offered = dispatch(absence_id)
    assert offered["current_offer_guard_id"] == sam["id"]
    assert_same_instant(offered["current_offer_expires_at"], "2026-09-16T01:45:00Z",
                        "AbsenceReport.current_offer_expires_at")
    assert never_dispatched["status"] == "DISPATCH_PENDING"

    stranger = api.respond_to_offer(absence_id, offer_response_payload("ACCEPT"),
                                    make_crossing_guard_headers(nia["id"]))
    validate_error(stranger, ApiErrorId.ERR_NOT_OFFER_RECIPIENT.value, 403)
    assert read_absence(absence_id)["status"] == "OFFER_OUT"

    no_offer = api.respond_to_offer(never_dispatched["id"],
                                    offer_response_payload("ACCEPT"),
                                    make_crossing_guard_headers(sam["id"]))
    state_error = validate_error(no_offer,
                                 ApiErrorId.ERR_NO_OPEN_OFFER.value, 409)
    assert state_error["error_id"] != ApiErrorId.ERR_NOT_OFFER_RECIPIENT.value
    assert read_absence(never_dispatched["id"])["status"] == "DISPATCH_PENDING"

    ticked = advance_clock("2026-09-16T01:46:00Z")
    assert_clock_response(ticked, "2026-09-16T01:46:00Z", activated=0, ended=0)
    assert read_absence(absence_id)["dispatch_offers"][0]["offer_status"] == "OPEN"

    too_late = api.respond_to_offer(absence_id, offer_response_payload("ACCEPT"),
                                    make_crossing_guard_headers(sam["id"]))

    validate_error(too_late, ApiErrorId.ERR_OFFER_EXPIRED.value, 409)
    stalled = read_absence(absence_id)
    assert stalled["status"] == "OFFER_OUT"
    assert stalled["substitute_guard_id"] is None
    assert stalled["substitute_cost_cents"] is None
    assert read_post(scenario["post"]["id"])["open_gap_count"] == 2


def test_neither_a_rescinded_report_nor_an_ended_assignment_can_be_acted_on(api):
    """Rescinding a rescission must not run the compensation twice, and once the
    clock has swept the assignment to ENDED a fresh filing is refused on the
    assignment's state even though the requested date sits inside its window.

    PRD: "It is accepted from `DISPATCH_PENDING`, `OFFER_OUT` or `UNCOVERED_GAP`;
    a report already `COVERED` or `RESCINDED` is refused with
    `ERR_ABSENCE_NOT_RESCINDABLE` (HTTP 409)." ... "The parent assignment's
    `status` must be `SCHEDULED` or `ACTIVE`; against a terminal assignment the
    refusal is `ERR_ASSIGNMENT_NOT_ACTIVE` (HTTP 409)."

    Design: Corner/errors/corner_terminal_absence_and_assignment_error_codes
    """
    scenario = setup_staffed_post()
    assignment_id = scenario["assignment"]["id"]
    absence = file_absence(assignment_id, absence_date="2026-09-16")
    withdrawn = rescind(absence["id"], reason="Guard reported for duty after all.")
    assert withdrawn["status"] == "RESCINDED"

    twice = api.rescind_absence_report(
        absence["id"],
        rescind_absence_payload(rescind_reason="Rescinding a rescission."),
        SUPERVISOR)
    validate_error(twice, ApiErrorId.ERR_ABSENCE_NOT_RESCINDABLE.value, 409)
    assert read_assignment(assignment_id)["open_absence_count"] == 0
    assert read_post(scenario["post"]["id"])["open_gap_count"] == 0

    swept = advance_clock("2026-09-19T00:00:00Z")
    assert_clock_response(swept, "2026-09-19T00:00:00Z", activated=1, ended=1)
    assert read_assignment(assignment_id)["status"] == "ENDED"

    after_the_end = api.create_absence_report(
        create_absence_report_payload(assignment_id, absence_date="2026-09-17",
                                      note="Filed after the window closed."),
        SUPERVISOR)

    error = validate_error(after_the_end,
                           ApiErrorId.ERR_ASSIGNMENT_NOT_ACTIVE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_ABSENCE_OUTSIDE_ASSIGNMENT.value
    rows, meta = validate_paginated(api.list_absence_reports(
        SUPERVISOR, {"post_assignment_id": assignment_id}))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [absence["id"]]
    assert rows[0]["status"] == "RESCINDED"


SCORING_CLOCK = "2026-09-30T09:00:00Z"


def test_the_funding_path_reports_four_different_refusals(api):
    """An unstudied location cannot be scored, a runner-up cannot be funded ahead
    of the leader, the leader cannot be funded beyond the pool, and a project that
    never received money cannot have it withdrawn — and the ledger is untouched by
    all four.

    PRD: "It also requires the project's intersection to carry a non-null
    `latest_warrant_score`: a project cannot be ranked before a warrant
    determination has been finalized at its location, and the refusal is
    `ERR_INTERSECTION_NOT_STUDIED` (HTTP 422)." ... "A target that is not the
    single top-ranked candidate is refused with `ERR_PROJECT_NOT_TOP_RANKED` (HTTP
    409)." ... "The project must be in `FUNDED`, or the refusal is
    `ERR_PROJECT_NOT_FUNDED` (HTTP 409)."

    Design: Corner/errors/corner_project_and_grant_error_codes
    """
    scenario = setup_warranted_intersection()
    advance_clock(SCORING_CLOCK)
    maple = read_intersection(scenario["intersection"]["id"])
    assert maple["latest_warrant_score"] == 66.19
    assert maple["crash_severity_points"] == 23
    birch = create_intersection(scenario["school"]["id"],
                                cross_streets="Birch St & 4th Ave")
    assert birch["warrant_status"] == "NOT_STUDIED"
    assert birch["latest_warrant_score"] is None
    program = create_grant_program(total_cents=2_000_000)
    leader = setup_scored_project(program["id"], maple["id"],
                                  requested_cost_cents=3_000_000,
                                  students_benefited=500)
    runner_up = setup_scored_project(program["id"], maple["id"],
                                     requested_cost_cents=2_000_000,
                                     students_benefited=300)
    unscored = propose_project(program["id"], birch["id"],
                               requested_cost_cents=1_000_000,
                               students_benefited=200)
    before = read_program(program["id"])
    assert leader["benefit_cost_score"] == 42.23
    assert runner_up["benefit_cost_score"] == 38.23

    unstudied = api.score_project(unscored["id"], ENGINEER)
    out_of_order = api.fund_project(
        runner_up["id"],
        fund_project_payload(before["version"],
                             award_note="Attempting the cheaper project first."),
        ADMIN)
    unaffordable = api.fund_project(
        leader["id"],
        fund_project_payload(before["version"],
                             award_note="Top-ranked but unaffordable."),
        ADMIN)
    nothing_to_release = api.withdraw_funding(
        leader["id"],
        withdraw_funding_payload(before["version"],
                                 withdrawal_reason="Nothing to withdraw."),
        ADMIN)

    validate_error(unstudied, ApiErrorId.ERR_INTERSECTION_NOT_STUDIED.value, 422)
    assert read_project(unscored["id"])["status"] == "PROPOSED"
    validate_error(out_of_order,
                   ApiErrorId.ERR_PROJECT_NOT_TOP_RANKED.value, 409)
    funds_error = validate_error(unaffordable,
                                 ApiErrorId.ERR_GRANT_FUNDS_EXHAUSTED.value, 402)
    assert funds_error["error_id"] != ApiErrorId.ERR_PROJECT_NOT_TOP_RANKED.value
    validate_error(nothing_to_release,
                   ApiErrorId.ERR_PROJECT_NOT_FUNDED.value, 409)
    after = read_program(program["id"])
    assert_grant_program(after)
    assert after["committed_cents"] == 0
    assert after["remaining_cents"] == 2_000_000
    assert after["funded_project_count"] == 0
    assert after["version"] == before["version"]
    intact = read_project(leader["id"])
    assert_infrastructure_project(intact)
    assert intact["status"] == "SCORED"
    assert intact["awarded_cents"] == 0
    assert intact["funded_at"] is None


def test_the_clock_may_stand_still_but_a_triaged_complaint_may_not_be_retriaged(api):
    """Re-setting the clock to the value it already holds is a legal no-op while any
    earlier instant is refused, and a second triage cannot overwrite the stored
    disposition or the engineer who recorded it.

    PRD: "The clock may only move forward or stay where it is: a `to_iso8601` value
    earlier than the current logical clock is rejected with
    `ERR_CLOCK_MOVED_BACKWARD` (HTTP 422)." ... "The complaint must be in
    `RECEIVED`, or the refusal is `ERR_COMPLAINT_NOT_TRIAGEABLE` (HTTP 409)." ...
    "A successful call returns a small object rather than a domain entity, carrying
    `current_utc` (the clock's new value), `activated_assignment_count` and
    `ended_assignment_count`."

    Design: Corner/errors/corner_clock_and_complaint_error_codes
    """
    school = create_school()
    intersection = create_intersection(school["id"])
    complaint = setup_triaged_complaint(intersection["id"])
    assert complaint["status"] == "TRIAGED"
    assert complaint["disposition"] == "REFER_TO_ENGINEERING"
    assert complaint["triaged_by_user_id"] == ENGINEER_USER_ID
    assert read_intersection(intersection["id"])["open_complaint_count"] == 1

    reversal = api.triage_complaint(
        complaint["id"],
        triage_complaint_payload("CLOSE_NO_ACTION",
                                 triage_note="Reversing the referral."),
        SECOND_ENGINEER)
    validate_error(reversal,
                   ApiErrorId.ERR_COMPLAINT_NOT_TRIAGEABLE.value, 409)
    frozen = read_complaint(complaint["id"])
    assert frozen["status"] == "TRIAGED"
    assert frozen["disposition"] == "REFER_TO_ENGINEERING"
    assert frozen["triaged_by_user_id"] == ENGINEER_USER_ID
    assert frozen["version"] == complaint["version"]
    assert read_intersection(intersection["id"])["open_complaint_count"] == 1

    forward = validate_success(api.set_clock("2026-09-01T00:00:00Z", ADMIN))
    assert_clock_response(forward, "2026-09-01T00:00:00Z", activated=0, ended=0)
    backward = api.set_clock("2026-08-15T00:00:00Z", ADMIN)
    validate_error(backward, ApiErrorId.ERR_CLOCK_MOVED_BACKWARD.value, 422)

    standstill = validate_success(api.set_clock("2026-09-01T00:00:00Z", ADMIN))

    assert_clock_response(standstill, "2026-09-01T00:00:00Z",
                          activated=0, ended=0)
