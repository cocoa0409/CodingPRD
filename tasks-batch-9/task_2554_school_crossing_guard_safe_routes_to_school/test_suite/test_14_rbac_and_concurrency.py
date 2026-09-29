"""Who may call what, and the three version tokens that guard a stale writer.

Authorization here is two-layered: a role gate on the endpoint, then identity
rules that compare the acting header against persisted data. These tests walk
the positive half of the matrix first so no later denial can be passed by a
blanket 403, then the cross-role denials, the two identity rules, and the
401/403 split. The second half exercises the three optimistic-concurrency
tokens of the program, and closes on the single absence that carries a guard
across the reliability floor.
"""
from test_helpers import (
    build_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_absence_report,
    assert_same_instant,
    assert_complaint,
    assert_grant_ledger_conserved,
    assert_grant_program,
    assert_guard,
    assert_infrastructure_project,
    assert_post_assignment,
    assert_walking_route,
    assert_warrant_study,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.factories import (
    certify_guard_payload,
    create_absence_report_payload,
    create_assignment_payload,
    create_complaint_payload,
    create_grant_program_payload,
    create_guard_post_payload,
    create_intersection_payload,
    create_walking_route_payload,
    create_warrant_study_payload,
    fund_project_payload,
    route_segment,
    triage_complaint_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    ENGINEER,
    REPORTER,
    SECOND_ENGINEER,
    SUPERVISOR,
    add_crash_records,
    create_active_post,
    create_assignment,
    create_grant_program,
    create_intersection,
    create_school,
    file_absence,
    file_complaint,
    read_absence,
    read_assignment,
    read_guard,
    read_intersection,
    read_post,
    read_program,
    read_project,
    read_study,
    setup_analyzed_study,
    setup_certified_guard,
    setup_guard_in_training,
    setup_published_route,
    setup_scored_project,
    setup_staffed_post,
    setup_warranted_intersection,
)
from test_helpers.test_users import (
    ADMIN_USER_ID,
    ENGINEER_USER_ID,
    SECOND_ENGINEER_USER_ID,
    make_crossing_guard_headers,
    make_school_liaison_headers,
)

NEAR_MISS_NARRATIVE = "A turning van missed a child in the crosswalk."


def test_five_roles_each_succeed_on_the_endpoint_they_own(api):
    """The positive half of the matrix: five roles, five endpoints each owned by
    exactly one of them, and not a single 403 among the five calls.

    PRD: "A `ProgramAdmin` is the municipal program administrator: they own the
    school and intersection registry, guard-post activation, the grant award
    decision, and the logical clock. A `TrafficEngineer` owns warrant analysis,
    crash data, complaint triage, engineering referrals and project scoring. A
    `CrossingSupervisor` owns the guard roster, certification, equipment issuance,
    post staffing and substitute dispatch." ... "A `SchoolLiaison` is the
    school-side program contact who drafts and publishes walking routes and files
    the term travel-tally survey. A `PublicReporter` is a member of the public
    whose write access is limited to filing a complaint."

    Design: Corner/rbac/corner_each_role_exercises_its_own_operations
    """
    scenario = setup_warranted_intersection()
    school_id = scenario["school"]["id"]
    intersection_id = scenario["intersection"]["id"]
    guard = setup_certified_guard()
    post = create_active_post(intersection_id)
    complaint = file_complaint(intersection_id)
    assert read_intersection(intersection_id)["open_complaint_count"] == 1

    program_response = api.create_grant_program(
        create_grant_program_payload(program_name="FY27 SRTS Infrastructure",
                                     total_cents=12_000_000,
                                     application_deadline="2026-10-15"), ADMIN)
    assignment_response = api.create_assignment(
        post["id"], create_assignment_payload(guard["id"], post["version"]),
        SUPERVISOR)
    triage_response = api.triage_complaint(
        complaint["id"],
        triage_complaint_payload("REFER_TO_ENGINEERING",
                                 triage_note="Speed study warranted."), ENGINEER)
    route_response = api.create_walking_route(
        create_walking_route_payload(school_id, route_code="RT-NORTH",
                                     route_name="North approach via Maple"),
        make_school_liaison_headers(school_id))
    complaint_response = api.create_complaint(
        intersection_id,
        create_complaint_payload(complaint_type="NEAR_MISS",
                                 reporter_name="Owen Park",
                                 occurred_at="2026-09-15T15:02:00Z",
                                 narrative=NEAR_MISS_NARRATIVE,
                                 severity_claim="HIGH"), REPORTER)

    responses = [program_response, assignment_response, triage_response,
                 route_response, complaint_response]
    assert [r.status_code for r in responses] == [201, 201, 200, 201, 201]
    program = validate_success(program_response, 201)
    assert_grant_program(program)
    assert program["remaining_cents"] == 12_000_000
    assignment = validate_success(assignment_response, 201)
    assert_post_assignment(assignment)
    assert assignment["status"] == "SCHEDULED"
    assert read_post(post["id"])["coverage_status"] == "COVERED"
    triaged = validate_success(triage_response)
    assert_complaint(triaged)
    assert triaged["status"] == "TRIAGED"
    assert triaged["triaged_by_user_id"] == ENGINEER_USER_ID
    route = validate_success(route_response, 201)
    assert_walking_route(route)
    assert route["status"] == "DRAFT"
    assert route["hazard_score"] == 1.66
    filed = validate_success(complaint_response, 201)
    assert filed["status"] == "RECEIVED"
    assert read_intersection(intersection_id)["open_complaint_count"] == 2


def test_four_operations_reject_the_role_that_does_not_own_them(api):
    """Each denial reaches across a different pair of roles, and because the role
    gate runs before the body is inspected none of the four targets moves.

    PRD: "If the headers are well formed but the named role is not authorized for
    the endpoint being called, the rejection is `ERR_UNAUTHORIZED` (HTTP 403).
    Authentication is always evaluated before authorization, and both are evaluated
    before the request body is inspected." ... "2. **Endpoint authorization** —
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/corner_cross_role_exclusive_operations_are_rejected
    """
    scenario = setup_staffed_post()
    school_id = scenario["school"]["id"]
    intersection_id = scenario["intersection"]["id"]
    proposed = validate_success(api.create_guard_post(
        create_guard_post_payload(intersection_id,
                                  post_label="Maple SE corner"), SUPERVISOR), 201)
    trainee = setup_guard_in_training(full_name="Tomas Reyes")
    absence = file_absence(scenario["assignment"]["id"])
    version_before = read_intersection(intersection_id)["version"]

    activate_response = api.activate_guard_post(proposed["id"], SUPERVISOR)
    certify_response = api.certify_guard(trainee["id"], certify_guard_payload(),
                                         ENGINEER)
    study_response = api.create_warrant_study(
        create_warrant_study_payload(intersection_id, version_before,
                                     count_window_start="2026-11-02",
                                     count_window_end="2026-11-20"),
        make_school_liaison_headers(school_id))
    dispatch_response = api.dispatch_absence_report(
        absence["id"], make_crossing_guard_headers(scenario["guard"]["id"]))

    for response in (activate_response, certify_response, study_response,
                     dispatch_response):
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    still_proposed = read_post(proposed["id"])
    assert still_proposed["status"] == "PROPOSED"
    assert still_proposed["activated_at"] is None
    untouched = read_guard(trainee["id"])
    assert untouched["certification_status"] == "IN_TRAINING"
    assert untouched["certification_expires_on"] is None
    _, meta = validate_paginated(
        api.list_intersection_warrant_studies(intersection_id, ENGINEER))
    assert meta["total_count"] == 1
    assert read_intersection(intersection_id)["version"] == version_before
    pending = read_absence(absence["id"])
    assert_absence_report(pending)
    assert pending["status"] == "DISPATCH_PENDING"
    assert pending["dispatch_attempt_count"] == 0
    assert pending["dispatch_offers"] == []


def test_the_authoring_engineer_is_blocked_but_a_second_one_is_not(api):
    """Segregation of duties is decided on the acting identity, not the role: the
    same endpoint, the same role and the same payload succeed under a second user.

    PRD: "The `TrafficEngineer` who opens a warrant study has their `X-User-ID`
    recorded as that study's `authored_by_user_id`, and the engineer who later
    adopts the study's determination onto the intersection must present a
    *different* `X-User-ID`. An attempt to finalize one's own study is rejected
    with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)." ... "On success the study's
    `status` moves to whichever of `WARRANTED`, `CONDITIONAL` or `NOT_WARRANTED`
    matches its pinned `determination`, `finalized_by_user_id` is set to the acting
    `X-User-ID`"

    Design: Corner/rbac/corner_finalize_by_authoring_engineer_is_rejected
    """
    scenario = setup_analyzed_study()
    study_id = scenario["study"]["id"]
    intersection_id = scenario["intersection"]["id"]
    assert scenario["study"]["status"] == "ANALYZED"
    assert scenario["study"]["warrant_score"] == 66.19
    assert scenario["study"]["determination"] == "WARRANTED"

    blocked = api.finalize_warrant_study(
        study_id, ENGINEER,
        {"engineer_note": "Self-adopting my own determination."})

    error = validate_error(blocked,
                           ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    assert error["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value
    held = read_study(study_id)
    assert held["status"] == "ANALYZED"
    assert held["finalized_by_user_id"] is None
    assert held["authored_by_user_id"] == ENGINEER_USER_ID
    unprojected = read_intersection(intersection_id)
    assert unprojected["warrant_status"] == "UNDER_STUDY"
    assert unprojected["latest_warrant_score"] is None

    adopted = validate_success(api.finalize_warrant_study(
        study_id, SECOND_ENGINEER,
        {"engineer_note": "Peer review complete; adopting WARRANTED."}))

    assert_warrant_study(adopted)
    assert adopted["status"] == "WARRANTED"
    assert adopted["finalized_by_user_id"] == SECOND_ENGINEER_USER_ID
    projected = read_intersection(intersection_id)
    assert projected["warrant_status"] == "WARRANTED"
    assert projected["latest_warrant_score"] == 66.19


def test_only_the_assigned_guard_may_file_that_assignments_absence(api):
    """The endpoint is shared by two roles, so the role gate cannot decide this: the
    ownership rule compares the acting header to the assignment's own guard.

    PRD: "a `CrossingGuard` filing an absence must be the guard named on the target
    assignment — `X-User-ID` must equal that assignment's `guard_id`, and a mismatch
    is `ERR_UNAUTHORIZED` (HTTP 403)" ... "`urgency_tier` follows from it:
    `SAME_DAY` when `notice_hours` is strictly below 12, `SHORT` when it is 12 or
    more but strictly below 48, and `STANDARD` when it is 48 or more."

    Design: Corner/rbac/corner_crossing_guard_cannot_file_another_guards_absence
    """
    scenario = setup_staffed_post()
    assignment_id = scenario["assignment"]["id"]
    stranger = setup_certified_guard(full_name="Nia Brandt")

    foreign = api.create_absence_report(
        create_absence_report_payload(
            assignment_id, absence_date="2026-09-16", reason="ILLNESS",
            note="Filed by a guard who does not hold this assignment."),
        make_crossing_guard_headers(stranger["id"]))

    validate_error(foreign, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert read_assignment(assignment_id)["open_absence_count"] == 0
    assert read_post(scenario["post"]["id"])["open_gap_count"] == 0

    own = validate_success(api.create_absence_report(
        create_absence_report_payload(
            assignment_id, absence_date="2026-09-16", reason="ILLNESS",
            note="Filed by the assigned guard."),
        make_crossing_guard_headers(scenario["guard"]["id"])), 201)

    assert_absence_report(own)
    assert own["status"] == "DISPATCH_PENDING"
    assert own["urgency_tier"] == "STANDARD"
    assert own["guard_id"] == scenario["guard"]["id"]
    assert read_assignment(assignment_id)["open_absence_count"] == 1
    assert read_post(scenario["post"]["id"])["open_gap_count"] == 1
    rows, meta = validate_paginated(api.list_absence_reports(
        SUPERVISOR, {"post_assignment_id": assignment_id}))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [own["id"]]


def test_the_public_reporter_is_denied_everything_but_intake_and_route_reads(api):
    """The narrowest role: a write it does not own and a read it does not own are
    both 403, while the published-route read on the same fixture is 200.

    PRD: "A `PublicReporter` is a member of the public whose write access is limited
    to filing a complaint." ... "Read one walking route, including per-segment
    hazard mapping and the aggregate hazard score. | ProgramAdmin, TrafficEngineer,
    CrossingSupervisor, SchoolLiaison, PublicReporter"

    Design: Corner/rbac/corner_public_reporter_write_and_read_surface_is_rejected_outside_intake
    """
    school = create_school()
    route = setup_published_route(school["id"])
    guard = setup_certified_guard()

    draft_response = api.create_walking_route(
        create_walking_route_payload(
            school["id"], segments=[route_segment(1, "NO_SIDEWALK", 100)],
            route_code="RT-SOUTH",
            route_name="South approach via Birch"), REPORTER)
    guard_response = api.get_guard(guard["id"], REPORTER)
    route_response = api.get_walking_route(route["id"], REPORTER)

    validate_error(draft_response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    validate_error(guard_response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    readable = validate_success(route_response)
    assert_walking_route(readable)
    assert readable["status"] == "PUBLISHED"
    assert readable["hazard_score"] == 1.66
    rows, meta = validate_paginated(
        api.list_school_walking_routes(school["id"], ADMIN))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [route["id"]]


def test_malformed_identity_headers_are_401_and_never_403(api):
    """Three ways to fail authentication — no role header, an undeclared role name
    and a blank user id — and none of them reaches the authorization band.

    PRD: "Every request must carry two headers: `X-User-ID`, identifying the acting
    user, and `X-User-Role`, naming that user's role. If either header is absent,
    empty, or if `X-User-Role` does not name one of the six roles below, the request
    is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)." ... "1. **Header presence
    and role validity** — `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/corner_missing_role_header_returns_unauthenticated
    """
    school = create_school()
    no_role_header = {"X-User-ID": ADMIN_USER_ID,
                      "Content-Type": "application/json"}
    undeclared_role = build_user_headers(ADMIN_USER_ID, "CrossingCaptain")
    blank_user_id = build_user_headers("", "ProgramAdmin")

    without_role = api.create_intersection(
        create_intersection_payload(school["id"]), no_role_header)
    unknown_role = api.create_intersection(
        create_intersection_payload(school["id"],
                                    cross_streets="Birch St & 4th Ave"),
        undeclared_role)
    without_user = api.create_intersection(
        create_intersection_payload(school["id"],
                                    cross_streets="Cedar St & 5th Ave"),
        blank_user_id)

    for response in (without_role, unknown_role, without_user):
        error = validate_error(response,
                               ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
        assert error["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value
        assert response.status_code != 403
    _, meta = validate_paginated(
        api.list_school_intersections(school["id"], ADMIN))
    assert meta["total_count"] == 0


def test_a_study_opened_on_a_stale_intersection_view_is_refused(api):
    """Both crash records bumped the intersection, so the version a client read one
    write ago buys nothing; the replay with the current token creates the study.

    PRD: "Opening a warrant study requires `expected_intersection_version`, carrying
    the client's last observed `version` of the target `Intersection`." ... "When
    `expected_intersection_version` does not match the intersection's current
    `version`, the create is rejected with `ERR_STALE_INTERSECTION_VERSION`
    (HTTP 412)." ... "A study is born in `DRAFT`, with an empty `count_sessions`
    array, `recount_round` at 0"

    Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_intersection_version_rejects_study_create
    """
    school = create_school()
    intersection = create_intersection(school["id"])
    current = add_crash_records(intersection["id"])
    assert current["crash_severity_points"] == 23
    assert current["version"] > intersection["version"]

    stale = api.create_warrant_study(
        create_warrant_study_payload(intersection["id"], current["version"] - 1),
        ENGINEER)

    validate_error(stale, ApiErrorId.ERR_STALE_INTERSECTION_VERSION.value, 412)
    unchanged = read_intersection(intersection["id"])
    assert unchanged["version"] == current["version"]
    assert unchanged["warrant_status"] == "NOT_STUDIED"
    assert unchanged["crash_severity_points"] == 23
    _, meta = validate_paginated(
        api.list_intersection_warrant_studies(intersection["id"], ENGINEER))
    assert meta["total_count"] == 0

    study = validate_success(api.create_warrant_study(
        create_warrant_study_payload(intersection["id"], current["version"]),
        ENGINEER), 201)

    assert_warrant_study(study)
    assert study["status"] == "DRAFT"
    assert study["recount_round"] == 0
    after = read_intersection(intersection["id"])
    assert after["version"] == current["version"] + 1
    assert after["warrant_status"] == "UNDER_STUDY"
    assert after["crash_severity_points"] == 23


def test_an_assignment_declaring_the_activation_era_post_version_is_refused(api):
    """The first assignment bumped the post, so the token captured at activation is
    one behind; the same otherwise-legal payload succeeds on the fresh version.

    PRD: "Creating a staffing assignment requires `expected_guard_post_version`,
    carrying the client's last observed `version` of the target `GuardPost`." ...
    "A mismatch is rejected with `ERR_STALE_GUARD_POST_VERSION` (HTTP 412)." ...
    "7. **Stale parent version** — the three guards of §2.9 (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_guard_post_version_rejects_assignment_create
    """
    scenario = setup_warranted_intersection()
    incumbent = setup_certified_guard()
    post = create_active_post(scenario["intersection"]["id"])
    first = create_assignment(post, incumbent["id"])
    fresh = read_post(post["id"])
    assert fresh["version"] == post["version"] + 1
    newcomer = setup_certified_guard(full_name="Nia Brandt")

    stale = api.create_assignment(
        post["id"],
        create_assignment_payload(newcomer["id"], post["version"],
                                  start_date="2026-09-21",
                                  end_date="2026-09-30"), SUPERVISOR)

    error = validate_error(stale,
                           ApiErrorId.ERR_STALE_GUARD_POST_VERSION.value, 412)
    assert error["error_id"] != ApiErrorId.ERR_ASSIGNMENT_OVERLAP.value
    _, meta = validate_paginated(api.list_post_assignments(
        SUPERVISOR, {"guard_post_id": post["id"]}))
    assert meta["total_count"] == 1
    assert read_guard(newcomer["id"])["duty_status"] == "UNASSIGNED"

    accepted = validate_success(api.create_assignment(
        post["id"],
        create_assignment_payload(newcomer["id"], fresh["version"],
                                  start_date="2026-09-21",
                                  end_date="2026-09-30"), SUPERVISOR), 201)

    assert_post_assignment(accepted)
    assert accepted["status"] == "SCHEDULED"
    assert accepted["shift"] == "AM"
    survivor = read_assignment(first["id"])
    assert survivor["status"] == "SCHEDULED"
    assert survivor["end_date"] == "2026-09-18"
    assert read_post(post["id"])["version"] == fresh["version"] + 1
    rows, meta = validate_paginated(api.list_post_assignments(
        SUPERVISOR, {"guard_post_id": post["id"]}))
    assert meta["total_count"] == 2
    assert [row["status"] for row in rows] == ["SCHEDULED", "SCHEDULED"]


def test_an_award_against_a_stale_program_balance_moves_no_money(api):
    """The third token guards money: the rejected award leaves the ledger opening,
    and the accepted one commits a quarter of the pool without draining it.

    PRD: "Both awarding grant funds to a project and withdrawing an award require
    `expected_grant_program_version`, carrying the client's last observed `version`
    of the `GrantProgram`." ... "A mismatch on either operation is rejected with
    `ERR_STALE_GRANT_PROGRAM_VERSION` (HTTP 412)." ... "The award moves the project
    `SCORED → FUNDED`, sets `awarded_cents` equal to `requested_cost_cents`, and
    stamps `funded_at` from the logical clock."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_grant_program_version_rejects_fund
    """
    scenario = setup_warranted_intersection()
    intersection_id = scenario["intersection"]["id"]
    program = create_grant_program(total_cents=12_000_000)
    leader = setup_scored_project(program["id"], intersection_id,
                                  requested_cost_cents=3_000_000,
                                  students_benefited=500)
    runner_up = setup_scored_project(program["id"], intersection_id,
                                     requested_cost_cents=2_000_000,
                                     students_benefited=300)
    opening = read_program(program["id"])
    assert leader["benefit_cost_score"] == 42.23
    assert runner_up["benefit_cost_score"] == 38.23

    stale = api.fund_project(
        leader["id"],
        fund_project_payload(opening["version"] - 1,
                             award_note="Awarding against a stale balance view."),
        ADMIN)

    validate_error(stale,
                   ApiErrorId.ERR_STALE_GRANT_PROGRAM_VERSION.value, 412)
    untouched = read_program(program["id"])
    assert_grant_ledger_conserved(untouched)
    assert untouched["committed_cents"] == 0
    assert untouched["remaining_cents"] == 12_000_000
    assert untouched["funded_project_count"] == 0
    assert untouched["version"] == opening["version"]
    unfunded = read_project(leader["id"])
    assert unfunded["status"] == "SCORED"
    assert unfunded["awarded_cents"] == 0
    assert unfunded["funded_at"] is None

    funded = validate_success(api.fund_project(
        leader["id"],
        fund_project_payload(opening["version"],
                             award_note="Awarding against the current balance."),
        ADMIN))

    assert_infrastructure_project(funded)
    assert funded["status"] == "FUNDED"
    assert funded["awarded_cents"] == 3_000_000
    assert_same_instant(funded["funded_at"], CLOCK_EPOCH,
                        "InfrastructureProject.funded_at")
    after = read_program(program["id"])
    assert_grant_program(after)
    assert after["committed_cents"] == 3_000_000
    assert after["remaining_cents"] == 9_000_000
    assert after["funded_project_count"] == 1
    assert after["deferred_project_count"] == 0
    assert after["version"] == opening["version"] + 1
    assert read_project(runner_up["id"])["status"] == "SCORED"


def test_the_third_unexcused_absence_suspends_the_guard_and_vacates_the_post(api):
    """Two unexcused absences hold the guard at 83.00 and CERTIFIED; the third costs
    another 10.0 rolling points and that single filing crosses the floor.

    PRD: "Its coefficients are 4.0 per absence and a further 6.0 per unexcused
    absence, so a single unexcused absence costs 10.0 points" ... "When a newly
    created absence report drops `reliability_score_rolling_90d` **strictly below
    75.00** for a guard whose `certification_status` is `CERTIFIED`, that guard moves
    `CERTIFIED → SUSPENDED` with `suspension_reason` set to `RELIABILITY_BREACH`, and
    a cascade follows: every assignment of that guard whose `status` is `SCHEDULED`
    or `ACTIVE` moves to `VACATED` with `vacated_reason` set to `GUARD_SUSPENDED`"

    Design: Corner/cross_cutting_complexity_layers/corner_third_unexcused_absence_crosses_the_reliability_floor
    """
    scenario = setup_staffed_post()
    assignment_id = scenario["assignment"]["id"]
    guard_id = scenario["guard"]["id"]
    for absence_date in ("2026-09-14", "2026-09-15"):
        file_absence(assignment_id, absence_date=absence_date,
                     reason="UNEXCUSED", note="No-show.")

    surviving = validate_success(api.get_guard(guard_id, SUPERVISOR))
    assert_guard(surviving)
    assert surviving["reliability_score_rolling_90d"] == 83.00
    assert surviving["reliability_score_season_to_date"] == 83.00
    assert surviving["certification_status"] == "CERTIFIED"

    third = validate_success(api.create_absence_report(
        create_absence_report_payload(assignment_id, absence_date="2026-09-16",
                                      reason="UNEXCUSED",
                                      note="Third no-show."), SUPERVISOR), 201)

    assert third["status"] == "DISPATCH_PENDING"
    breached = read_guard(guard_id)
    assert breached["reliability_score_rolling_90d"] == 73.00
    assert breached["reliability_score_season_to_date"] == 73.00
    assert breached["certification_status"] == "SUSPENDED"
    assert breached["suspension_reason"] == "RELIABILITY_BREACH"
    assert breached["duty_status"] == "UNASSIGNED"
    vacated = read_assignment(assignment_id)
    assert vacated["status"] == "VACATED"
    assert vacated["vacated_reason"] == "GUARD_SUSPENDED"
    assert read_post(scenario["post"]["id"])["coverage_status"] == "UNSTAFFED"
    _, meta = validate_paginated(api.list_absence_reports(
        SUPERVISOR, {"post_assignment_id": assignment_id}))
    assert meta["total_count"] == 3
