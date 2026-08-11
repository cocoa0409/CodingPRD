"""Ladder precedence between rungs, and role / ownership enforcement."""

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID_A,
    book_session,
    complete_session,
    confirm_session,
    draft_progress_note,
    file_incident,
    headers_with_unknown_role,
    headers_without_role,
    make_goal,
    make_instructor_headers,
    make_period_report,
    read_goal,
    read_progress_note,
    read_rider,
    session_payload,
    set_clock,
    setup_active_rider,
    setup_horse_week_at_240,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, CLERK, COORD

TWO_HORSES = [
    {"name": "Comet", "body_weight_lb": 1100, "tack_weight_lb": 30},
    {"name": "Blaze", "body_weight_lb": 1100, "tack_weight_lb": 30},
]
TWO_MASTERS = [
    {
        "full_name": "Ada Reins",
        "certification_level": "MASTER",
        "certification_expires_at": "2028-04-30T00:00:00Z",
    },
    {
        "full_name": "Bo Bridle",
        "certification_level": "MASTER",
        "certification_expires_at": "2028-04-30T00:00:00Z",
    },
]


def _rider_on_incident_hold():
    """A SEV_1 fall puts the rider on a medical hold; a second horse and instructor stay clean."""
    scenario = setup_active_rider(horses=TWO_HORSES, instructors=TWO_MASTERS)
    session = book_session(
        scenario["rider_id"], scenario["horse_ids"][0], scenario["instructor_ids"][0]
    )
    confirm_session(session["id"], scenario["instructor_ids"][0])
    set_clock("2026-05-11T11:30:00Z")
    complete_session(session["id"], scenario["instructor_ids"][0], 60)
    scenario["incident"] = file_incident(
        session["id"],
        scenario["instructor_ids"][0],
        incident_type="FALL",
        injury_reported=True,
        occurred_at="2026-05-11T10:30:00Z",
        narrative="Fall with reported pain",
    )
    return scenario


def test_incident_hold_gate_outranks_the_rider_state_rung(api):
    """PRD 2.7 rung 14: "**Gate 1 — incident hold.** No subject the write touches
    carries a hold placed by an incident whose `status` is `OPEN` or
    `UNDER_REVIEW` — otherwise `ERR_INCIDENT_HOLD_ACTIVE` (409)."
    PRD 3.9: "While an incident is `OPEN` or `UNDER_REVIEW`, every hold it placed
    is the highest-precedence refusal in the system: any booking, confirmation,
    completion or crew assignment touching a held rider, horse, volunteer or
    instructor is refused with `ERR_INCIDENT_HOLD_ACTIVE` before any other check
    is reached."

    Design: Difficulty/priority_pair_validation_conflict/incident_hold_gate_outranks_rider_not_active_state_rung
    """
    scenario = _rider_on_incident_hold()
    assert read_rider(scenario["rider_id"])["status"] == "MEDICAL_HOLD"

    response = api.create_session(
        session_payload(
            scenario["rider_id"],
            scenario["horse_ids"][1],
            scenario["instructor_ids"][1],
            scheduled_start="2026-05-20T10:00:00Z",
        ),
        make_instructor_headers(scenario["instructor_ids"][1]),
    )
    validate_error(response, ApiErrorId.ERR_INCIDENT_HOLD_ACTIVE.value, expected_status=409)


def test_no_session_is_created_when_the_incident_gate_fires(api):
    """PRD 2.7: "Every request is evaluated against one ladder of 44 rungs, in
    ascending rung number, and the **first** rung whose condition fails
    determines the response. There are no independent or unordered checks
    anywhere in this API: whenever two rungs would both reject a request, the
    lower-numbered rung's error is the one returned, and the higher-numbered rung
    is never reached."
    PRD 2.8: "Second, the gates sit above every domain rule that follows them, so
    a session creation that would also breach the horse's weekly minutes but
    whose rider is on an incident hold reports `ERR_INCIDENT_HOLD_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/incident_hold_gate_outranks_rider_not_active_state_rung
    """
    scenario = _rider_on_incident_hold()

    response = api.create_session(
        session_payload(
            scenario["rider_id"],
            scenario["horse_ids"][1],
            scenario["instructor_ids"][1],
            scheduled_start="2026-05-20T10:00:00Z",
        ),
        make_instructor_headers(scenario["instructor_ids"][1]),
    )
    error = response.json()["data"]["error_id"]
    assert error != ApiErrorId.ERR_RIDER_NOT_ACTIVE.value, (
        "Rung 14 pre-empts rung 20 even though the rider sits in MEDICAL_HOLD"
    )
    assert error == ApiErrorId.ERR_INCIDENT_HOLD_ACTIVE.value

    rows, _ = validate_paginated(
        api.list_sessions(ADMIN, params={"rider_id": scenario["rider_id"]})
    )
    assert all(row["scheduled_start"][:10] != "2026-05-20" for row in rows)


def test_horse_overlap_outranks_the_weekly_minutes_rung(api):
    """PRD 2.7 rung 28: "The new session's half-open time interval does not
    intersect the half-open interval of another live session of the same horse —
    otherwise `ERR_HORSE_SCHEDULE_CONFLICT` (409). Applies to session creation."
    PRD 2.7: "whenever two rungs would both reject a request, the lower-numbered
    rung's error is the one returned, and the higher-numbered rung is never
    reached."

    Design: Difficulty/priority_pair_validation_conflict/horse_overlap_temporal_rung_outranks_weekly_minutes_constraint_rung
    """
    scenario = setup_horse_week_at_240(setup_active_rider())

    response = api.create_session(
        session_payload(
            scenario["rider_id"],
            scenario["horse_id"],
            scenario["instructor_id"],
            scheduled_start="2026-05-12T09:30:00Z",
        ),
        scenario["instructor_headers"],
    )
    validate_error(
        response, ApiErrorId.ERR_HORSE_SCHEDULE_CONFLICT.value, expected_status=409
    )


def test_the_weekly_ledger_is_untouched_by_the_rejected_booking(api):
    """PRD 2.7 rung 31: "The horse's committed minutes for the week, including
    the new session's `duration_minutes`, are at most 240 — otherwise
    `ERR_HORSE_WEEKLY_MINUTES_EXCEEDED` (422). Applies to session creation."
    PRD 3.3: "answering with the `horse_id`, the echoed `on_date`, the
    `week_start_date` for that date, the `variant` used, the `day_session_count`,
    the `day_minutes`, the `week_minutes`, and the headroom figures
    `day_remaining_minutes` (150 minus `day_minutes`) and `week_remaining_minutes`
    (240 minus `week_minutes`)."

    Design: Difficulty/priority_pair_validation_conflict/horse_overlap_temporal_rung_outranks_weekly_minutes_constraint_rung
    """
    scenario = setup_horse_week_at_240(setup_active_rider())

    response = api.create_session(
        session_payload(
            scenario["rider_id"],
            scenario["horse_id"],
            scenario["instructor_id"],
            scheduled_start="2026-05-12T09:30:00Z",
        ),
        scenario["instructor_headers"],
    )
    error = response.json()["data"]["error_id"]
    assert error != ApiErrorId.ERR_HORSE_WEEKLY_MINUTES_EXCEEDED.value, (
        "The temporal rung 28 wins even though 240 + 60 would breach the week"
    )
    assert error == ApiErrorId.ERR_HORSE_SCHEDULE_CONFLICT.value

    workload = validate_success(
        api.get_horse_workload(
            scenario["horse_id"],
            ADMIN,
            params={"on_date": "2026-05-12", "variant": "committed"},
        )
    )
    assert workload["week_minutes"] == 240
    assert workload["week_remaining_minutes"] == 0


def test_missing_role_header_is_unauthenticated(api):
    """PRD 2.1: "Every request to every endpoint must carry two headers:
    `X-User-ID` and `X-User-Role`. If either header is absent or empty, the
    request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/get_riders_missing_x_user_role_header_returns_401
    """
    set_clock("2026-05-01T00:00:00Z")

    response = api.list_riders(headers_without_role())
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


def test_undeclared_role_is_unauthenticated_not_unauthorized(api):
    """PRD 2.1: "The same error is returned when `X-User-Role` carries a value
    that is not one of the five roles the centre recognises. Those five roles,
    spelled exactly as they must appear in the header, are `ProgramAdmin`,
    `Instructor`, `VolunteerCoordinator`, `IntakeCoordinator` and `BillingClerk`."

    Design: Corner/rbac/get_riders_with_an_undeclared_role_returns_401
    """
    set_clock("2026-05-01T00:00:00Z")

    response = api.list_riders(headers_with_unknown_role(role="BarnManager"))
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value


def test_volunteer_coordinator_cannot_book_a_session(api):
    """PRD 2.1: "When the role is recognised but is not among the roles
    authorised for the endpoint being called, the rejection is
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD 2.1: "`VolunteerCoordinator` owns the volunteer roster, the qualification
    matrix and session crewing, and is the only role that may release a crew
    assignment, record annual re-training, or read the volunteer service-hours
    ledger; the coordinator may never book, confirm, complete or cancel a
    session."

    Design: Corner/rbac/volunteer_coordinator_cannot_book_a_session
    """
    scenario = setup_active_rider()

    response = api.create_session(
        session_payload(
            scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
        ),
        COORD,
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)

    _, meta = validate_paginated(api.list_sessions(ADMIN))
    assert meta["total_count"] == 0


def test_instructor_cannot_complete_a_colleagues_session(api):
    """PRD 2.1: "Completing a session requires `X-User-ID` to equal that
    session's `instructor_id`, and finalizing a progress note requires
    `X-User-ID` to equal that note's `author_instructor_id`; in both cases
    another `Instructor` attempting the operation is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403), which is the same code an unauthorised role
    receives."

    Design: Corner/rbac/instructor_cannot_complete_a_session_taught_by_a_colleague
    """
    scenario = setup_active_rider(instructors=TWO_MASTERS)
    teacher_id, colleague_id = scenario["instructor_ids"]
    session = book_session(scenario["rider_id"], scenario["horse_id"], teacher_id)
    confirm_session(session["id"], teacher_id)

    refused = api.complete_session(
        session["id"], {"mounted_minutes": 60}, make_instructor_headers(colleague_id)
    )
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)

    _, before = validate_paginated(
        api.list_charges(CLERK, params={"session_id": session["id"]})
    )
    assert before["total_count"] == 0

    completed = validate_success(
        api.complete_session(
            session["id"], {"mounted_minutes": 60}, make_instructor_headers(teacher_id)
        )
    )
    assert completed["schedule_status"] == "COMPLETED"
    _, after = validate_paginated(
        api.list_charges(CLERK, params={"session_id": session["id"]})
    )
    assert after["total_count"] == 1


def test_instructor_cannot_finalize_a_colleagues_note(api):
    """PRD 2.1: "Completing a session requires `X-User-ID` to equal that
    session's `instructor_id`, and finalizing a progress note requires
    `X-User-ID` to equal that note's `author_instructor_id`; in both cases
    another `Instructor` attempting the operation is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403), which is the same code an unauthorised role
    receives."
    PRD 2.1: "Drafting a progress note likewise records the caller:
    `author_instructor_id` is taken from `X-User-ID` and is never accepted from
    the request body."

    Design: Corner/rbac/instructor_cannot_finalize_a_note_authored_by_a_colleague
    """
    scenario = setup_active_rider(instructors=TWO_MASTERS)
    author_id, colleague_id = scenario["instructor_ids"]
    goal = make_goal(
        scenario["rider_id"],
        author_id,
        domain="PHYSICAL",
        objective="Independent halt",
        baseline_rating=1,
        target_rating=3,
    )
    session = book_session(scenario["rider_id"], scenario["horse_id"], author_id)
    confirm_session(session["id"], author_id)
    complete_session(session["id"], author_id, 60)
    note = draft_progress_note(
        session["id"],
        author_id,
        narrative="Great control today",
        goal_ratings=[{"goal_id": goal["id"], "rating": 3}],
    )
    assert note["author_instructor_id"] == author_id

    refused = api.finalize_progress_note(
        note["id"], make_instructor_headers(colleague_id)
    )
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)

    assert read_progress_note(note["id"])["status"] == "DRAFT"
    assert read_goal(goal["id"])["current_rating"] is None


def test_billing_clerk_cannot_finalize_a_period_report(api):
    """PRD 2.1: "When the role is recognised but is not among the roles
    authorised for the endpoint being called, the rejection is
    `ERR_UNAUTHORIZED` (HTTP 403). §4 lists the authorised roles for each
    endpoint."
    PRD 2.1: "`ProgramAdmin` is the centre operations lead. The role owns the
    barn, the certification register, the money register and the reporting
    period"

    Design: Corner/rbac/billing_clerk_cannot_finalize_a_period_report
    """
    set_clock("2026-05-01T00:00:00Z")
    report = make_period_report(period_start="2026-05-01", period_end="2026-05-31")

    read_back = validate_success(api.get_period_report(report["id"], CLERK))
    assert read_back["status"] == "DRAFT", "The BillingClerk may read the report"

    refused = api.finalize_period_report(report["id"], CLERK)
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)

    unchanged = validate_success(api.get_period_report(report["id"], ADMIN))
    assert unchanged["status"] == "DRAFT"
    assert unchanged["finalized_at"] is None


def test_get_grant_with_unknown_id_is_generic_resource_not_found(api):
    """PRD 2.7 rung 12: "Every other path identifier resolves, checked left to
    right along the URL — otherwise `ERR_RESOURCE_NOT_FOUND` (404). The
    identifiers in this class are `{release_id}`, `{assessment_id}`,
    `{volunteer_id}`, `{qualification_id}`, `{instructor_id}`, `{assignment_id}`,
    `{goal_id}`, `{note_id}`, `{grant_id}`, `{award_id}`, `{charge_id}`,
    `{allocation_id}`, `{incident_id}` and `{report_id}`."

    Design: Corner/entities/get_grant_with_unknown_uuid_returns_generic_resource_not_found
    """
    set_clock("2026-05-01T00:00:00Z")

    response = api.get_grant(UNKNOWN_UUID_A, ADMIN)
    validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value, expected_status=404)
