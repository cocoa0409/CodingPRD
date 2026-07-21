"""Homebuyer-education enrollment: applicant-scoped session-time conflict,
capacity enforcement, and session-time validity.

Difficulty:
  resource_temporal_overlap / session_enrollment_overlap_for_applicant
Corner:
  validations / enroll_into_full_session_returns_error
  validations / create_session_bad_times_returns_invalid
"""
from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.test_users import make_applicant_headers
from test_helpers.factories import create_education_session_payload

PROGRAM_ADMIN = fx.PROGRAM_ADMIN


# --- resource_temporal_overlap / session_enrollment_overlap_for_applicant ---
def test_session_enrollment_within_buffer_conflicts(api):
    """PRD 3.3: "two sessions conflict when the other session's `start_at` is
    earlier than this session's `end_at` plus 30 minutes and this session's
    `start_at` is earlier than the other session's `end_at` plus 30 minutes; a
    conflict is rejected with `ERR_SESSION_TIME_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/session_enrollment_overlap_for_applicant
    """
    program = fx.new_program(api)
    applicant = fx.new_applicant(api)
    s1 = fx.new_education_session(
        api, program["id"], title="S1", start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:00:00Z"
    )
    s2 = fx.new_education_session(
        api, program["id"], title="S2", start_at="2026-07-10T12:15:00Z", end_at="2026-07-10T14:00:00Z"
    )
    fx.enroll(api, s1["id"], applicant["id"])
    # s2.start 12:15 < s1.end 12:00 + 30m = 12:30  => conflict.
    resp = api.create_enrollment(s2["id"], {"applicant_id": applicant["id"]}, make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_SESSION_TIME_CONFLICT.value)


def test_session_enrollment_exactly_buffer_apart_allowed(api):
    """PRD 3.3: "two sessions conflict when the other session's `start_at` is
    earlier than this session's `end_at` plus 30 minutes and this session's
    `start_at` is earlier than the other session's `end_at` plus 30 minutes; a
    conflict is rejected with `ERR_SESSION_TIME_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/session_enrollment_overlap_for_applicant
    """
    program = fx.new_program(api)
    applicant = fx.new_applicant(api)
    s1 = fx.new_education_session(
        api, program["id"], title="S1", start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:00:00Z"
    )
    # s2.start 12:30 is NOT earlier than s1.end 12:00 + 30m = 12:30 => no conflict.
    s2 = fx.new_education_session(
        api, program["id"], title="S2", start_at="2026-07-10T12:30:00Z", end_at="2026-07-10T14:00:00Z"
    )
    fx.enroll(api, s1["id"], applicant["id"])
    resp = api.create_enrollment(s2["id"], {"applicant_id": applicant["id"]}, make_applicant_headers(applicant["id"]))
    data = validate_success(resp, 201)
    assert data["status"] == "ENROLLED"


# --- Corner / enroll_into_full_session_returns_error ------------------------
def test_enroll_into_full_session_returns_error(api):
    """PRD 3.3: "capacity is enforced: the session's `enrolled_count` must be
    strictly less than its `capacity`, otherwise the enrollment is rejected with
    `ERR_SESSION_FULL` (HTTP 409)."

    Design: Corner/validations/enroll_into_full_session_returns_error
    """
    program = fx.new_program(api)
    a1 = fx.new_applicant(api)
    a2 = fx.new_applicant(api)
    session = fx.new_education_session(
        api, program["id"], title="Cap1", start_at="2026-07-10T09:00:00Z",
        end_at="2026-07-10T12:00:00Z", capacity=1,
    )
    fx.enroll(api, session["id"], a1["id"])
    resp = api.create_enrollment(session["id"], {"applicant_id": a2["id"]}, make_applicant_headers(a2["id"]))
    validate_error(resp, ApiErrorId.ERR_SESSION_FULL.value)


# --- Corner / create_session_bad_times_returns_invalid ----------------------
def test_create_session_bad_times_returns_invalid(api):
    """PRD 3.3: "The `end_at` must be strictly later than `start_at`; a session
    whose end is at or before its start is rejected with
    `ERR_SESSION_TIME_INVALID` (HTTP 400)."

    Design: Corner/validations/create_session_bad_times_returns_invalid
    """
    program = fx.new_program(api)
    payload = create_education_session_payload(
        program_id=program["id"], title="Bad",
        start_at="2026-07-10T12:00:00Z", end_at="2026-07-10T09:00:00Z",
    )
    resp = api.create_education_session(payload, PROGRAM_ADMIN)
    validate_error(resp, ApiErrorId.ERR_SESSION_TIME_INVALID.value)
