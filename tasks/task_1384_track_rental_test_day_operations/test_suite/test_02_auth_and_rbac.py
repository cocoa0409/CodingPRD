"""Authentication, authorization, and role-based access control."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, NON_EXISTENT_UUID, NO_ROLE_HEADERS,
    create_track_payload,
    make_track, make_open_track_day, make_block, make_booking,
    block_version, setup_running_day_with_session, setup_stopped_day_via_incident,
    report_incident, investigate_and_clear, resume_day, get_day,
    TEST_USERS, make_organizer_headers,
)

OPS = TEST_USERS["trackops_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]
COACH = TEST_USERS["coach_headers"]


def test_unauthenticated_request_returns_401(api):
    """PRD §2.1: "A request arriving with a missing or unknown `X-User-Role`
    is rejected with `ERR_UNAUTHENTICATED` (401); a caller whose role is not
    on an endpoint's authorized list is rejected with `ERR_FORBIDDEN_ROLE`
    (403)."

    Design: Corner/validations/unauthenticated_request_returns_401
    """
    resp = api.get_track(NON_EXISTENT_UUID, NO_ROLE_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_forbidden_role_returns_403(api):
    """PRD §2.1: "a caller whose role is not on an endpoint's authorized list
    is rejected with `ERR_FORBIDDEN_ROLE` (403)." PRD §2.1: "`Coach` — a
    driving coach: read-only across the API."

    Design: Corner/validations/forbidden_role_returns_403
    """
    resp = api.create_track(create_track_payload(name="V2"), COACH)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_forbidden_role_for_safety_officer_attempting_track_create(api):
    """PRD §3.1: "A `TrackOps` operator registers a track with its `name` and
    four operating parameters". PRD §2.1: "a caller whose role is not on an
    endpoint's authorized list is rejected with `ERR_FORBIDDEN_ROLE` (403)."

    Design: Corner/errors/err_forbidden_role_for_safety_officer_attempting_track_create
    """
    resp = api.create_track(create_track_payload(name="X"), SAFETY)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_organizer_cannot_approve_booking(api):
    """PRD §3.3: "Approval is a `TrackOps` decision and the most heavily gated
    write in the system." PRD §2.1: "a caller whose role is not on an
    endpoint's authorized list is rejected with `ERR_FORBIDDEN_ROLE` (403)."

    Design: Corner/rbac/organizer_cannot_approve_booking
    """
    track = make_track(name="R1")
    day = make_open_track_day(track["id"], "2026-10-02")
    block = make_block(track["id"], day["id"])
    booking = make_booking(track["id"], day["id"], block["id"], "oR1")
    resp = api.approve_booking(
        track["id"], day["id"], block["id"], booking["id"],
        {"expected_rental_block_version": block_version(
            track["id"], day["id"], block["id"])},
        make_organizer_headers("oR1"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_trackops_cannot_clear_incident(api):
    """PRD §3.6: "Incident resolution is `SafetyOfficer` work, with two steps
    available." PRD §2.1: "a caller whose role is not on an endpoint's
    authorized list is rejected with `ERR_FORBIDDEN_ROLE` (403)."

    Design: Corner/rbac/trackops_cannot_clear_incident
    """
    env = setup_running_day_with_session("2026-10-03")
    tid, tdid = env["track"]["id"], env["day"]["id"]
    incident = report_incident(tid, tdid, env["session"]["id"], "LOW", "oR2")
    resp = api.clear_incident(tid, tdid, incident["id"],
                              {"cleared_by_user_id": "safetyR2"}, OPS)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_safety_officer_resume_is_permitted(api):
    """PRD §3.6: "Resuming a stopped day is exclusively `SafetyOfficer`
    authority and is version-guarded: the request carries
    `expected_track_day_version` matching the day's current `version`, and a
    stale value is rejected with `ERR_STALE_VERSION` (412) — a prior resume or
    a fresh incident may already have moved the day past the client's last
    read." PRD §3.6: "A successful resume moves the day from `STOPPED` back to
    `RUNNING`, returns every `RED` session to `GREEN`, recomputes posture —
    `NORMAL` or `CAUTION` depending on the remaining breach count — and
    advances the day's `version` by one."

    Design: Corner/rbac/safety_officer_cannot_resume_via_trackops_endpoint
    """
    env = setup_stopped_day_via_incident("2026-10-04", severity="HIGH",
                                         reporter="opsR3")
    tid, tdid = env["track"]["id"], env["day"]["id"]
    assert env["day"]["status"] == "STOPPED"
    investigate_and_clear(tid, tdid, env["incident"]["id"], "safetyR3")
    resumed = resume_day(tid, tdid)  # issued with SafetyOfficer headers
    assert resumed["status"] == "RUNNING"
    assert validate_success(api.get_track_day(tid, tdid, SAFETY))["status"] == "RUNNING"
