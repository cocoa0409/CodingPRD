"""Training sessions, enrollments, the certification ladder, and enrolled-count
reconciliation.

Translates queue B (Corner) instances touching enrollment attendance and session
capacity.
"""
import test_helpers as th
from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers.test_users import make_member_headers


def test_basic_cert_attendance_requires_orientation(api, staff):
    """PRD §3.5: "For a `BASIC_CERT` session, the member must already have completed
    orientation — otherwise attendance is rejected with `ERR_ORIENTATION_REQUIRED` —
    and on success the member's `certification_level` is set to `BASIC`."

    Design: Corner/validations/basic_cert_attendance_requires_orientation
    """
    th.make_tier("SAIL")
    dock = th.make_dock()
    m = th.make_member("SAIL", dock["id"])["id"]  # PENDING_ORIENTATION, never oriented
    session = th.make_session(dock["id"], "BASIC_CERT", ("2026-05-02T12:00:00Z", "2026-05-02T14:00:00Z"))
    enr = th.enroll(m, session["id"])

    resp = api.mark_attendance(enr["id"], {"attended": True}, staff)
    validate_error(resp, ApiErrorId.ERR_ORIENTATION_REQUIRED)
    assert th.get_member(m)["certification_level"] == "NONE", "cert must not be granted"


def test_session_reaches_full_and_rejects_over_capacity(api, admin):
    """PRD §3.5: "When enrollments bring `enrolled_count` up to `capacity`, the
    session automatically moves from `SCHEDULED` to `FULL`"
    PRD §3.5: "no one may enroll in a session already at capacity, which is rejected
    with `ERR_SESSION_FULL` (HTTP 409)."

    Design: Corner/cross_cutting_complexity_layers/derived_session_enrolled_count_reconciled
    """
    th.make_tier("SAIL")
    dock = th.make_dock()
    m1 = th.make_member("SAIL", dock["id"], "M1", "m1@x.com")["id"]
    m2 = th.make_member("SAIL", dock["id"], "M2", "m2@x.com")["id"]
    session = th.make_session(dock["id"], "ORIENTATION", ("2026-05-02T09:00:00Z", "2026-05-02T11:00:00Z"), capacity=1)

    th.enroll(m1, session["id"])
    s = validate_success(api.get_training_session(session["id"], admin), 200)
    assert s["enrolled_count"] == 1
    assert s["status"] == "FULL"

    resp = api.create_enrollment(th.create_enrollment_payload(m2, session["id"]), make_member_headers(m2))
    validate_error(resp, ApiErrorId.ERR_SESSION_FULL)


def test_duplicate_enrollment_rejected(api):
    """PRD §3.5: "A member may not hold two live enrollments in the same session — a
    second, non-terminal enrollment is rejected as a duplicate with
    `ERR_DUPLICATE_ENROLLMENT` (HTTP 409)"

    Design: Corner/cross_cutting_complexity_layers/duplicate_enrollment_rejected
    """
    th.make_tier("SAIL")
    dock = th.make_dock()
    m = th.make_member("SAIL", dock["id"])["id"]
    session = th.make_session(dock["id"], "ORIENTATION", ("2026-05-02T09:00:00Z", "2026-05-02T11:00:00Z"))
    th.enroll(m, session["id"])

    resp = api.create_enrollment(th.create_enrollment_payload(m, session["id"]), make_member_headers(m))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENROLLMENT)
