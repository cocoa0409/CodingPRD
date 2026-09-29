"""Trainers, class sessions, servers, enrollments and exam attempts."""

from flask import Blueprint

import chain
import domain
import envelope
import store as st
import validate as v
from auth import (
    authenticate, deny_ownership, ALCOHOL_SERVER, EMPLOYER_ADMIN, PROGRAM_ADMIN,
    STATE_REGULATOR, TRAINER,
)
from calcs import score_pct
from errors import fail, invalid
from store import apply_changes, create_row, store

bp = Blueprint("training", __name__)

BUFFER_MINUTES = 60
LIVE_SESSION_STATES = ("SCHEDULED", "ROSTER_LOCKED", "EXAM_OPEN")


def paged(items):
    limit, offset = v.pagination()
    page, total = envelope.paginate(items, limit, offset)
    return envelope.ok_list(page, limit, offset, total)


def own_session(caller, session):
    """Priority 5 for the instructing-trainer transitions."""
    if caller.is_trainer and caller.user_id != session["trainer_id"]:
        deny_ownership()


def own_proctor(caller, session):
    if caller.is_trainer and caller.user_id != session.get("proctor_trainer_id"):
        deny_ownership()


# --- trainers --------------------------------------------------------------

@bp.post("/trainers")
def create_trainer():
    authenticate((PROGRAM_ADMIN,))
    body = v.body()
    full_name = v.req_str(body, "full_name", 1, 120)
    email = v.req_email(body, "email")
    for row in st.rows("trainers"):                                    # priority 24
        if row["email"] == email:
            fail("ERR_IDENTITY_ALREADY_REGISTERED",
                 "email '%s' is already registered." % email)
    row = create_row("trainers", {
        "full_name": full_name,
        "email": email,
        "trainer_status": "PROVISIONAL",
        "certified_tracks": [],
        "certified_state_codes": [],
        "credential_expires_at": None,
        "sessions_taught_count": 0,
        "graded_enrollments_count": 0,
        "pass_rate_pct": v.quantize(0, 2),
        "suspension_reason": None,
    })
    return envelope.ok_row(row, 201)


@bp.post("/trainers/<trainer_id>/credential")
def credential_trainer(trainer_id):
    authenticate((PROGRAM_ADMIN,))
    body = v.body()
    tracks = v.req_enum_array(body, "certified_tracks", v.TRACKS, allow_empty=False)
    state_codes = v.req_string_array(body, "certified_state_codes", allow_empty=False)
    expires_at = v.req_dt(body, "credential_expires_at")
    if expires_at <= store.clock:
        invalid("Field 'credential_expires_at' must be after the current time.")
    trainer = v.must_exist("trainers", trainer_id)
    if trainer["trainer_status"] == "SUSPENDED":                       # priority 12
        fail("ERR_TRAINER_INVALID_STATE", "A SUSPENDED trainer cannot be credentialed.")
    apply_changes(trainer, {
        "certified_tracks": tracks,
        "certified_state_codes": state_codes,
        "credential_expires_at": expires_at,
        "trainer_status": "CERTIFIED",
    })
    return envelope.ok_row(trainer)


@bp.post("/trainers/<trainer_id>/suspend")
def suspend_trainer(trainer_id):
    authenticate((PROGRAM_ADMIN,))
    body = v.body()
    suspension_reason = v.opt_str(body, "suspension_reason", 1, None)
    trainer = v.must_exist("trainers", trainer_id)
    if trainer["trainer_status"] == "SUSPENDED":                       # priority 12
        fail("ERR_TRAINER_INVALID_STATE", "The trainer is already SUSPENDED.")
    domain.suspend_trainer(trainer, suspension_reason)
    return envelope.ok_row(trainer)


@bp.get("/trainers/<trainer_id>")
def read_trainer(trainer_id):
    authenticate((PROGRAM_ADMIN, STATE_REGULATOR, TRAINER))
    return envelope.ok_row(v.must_exist("trainers", trainer_id))


# --- class sessions --------------------------------------------------------

def _trainer_qualified(trainer, track, state_code, horizon):
    if trainer["trainer_status"] != "CERTIFIED":
        return False
    if track not in trainer["certified_tracks"]:
        return False
    if state_code not in trainer["certified_state_codes"]:
        return False
    if trainer["credential_expires_at"] is None:
        return False
    return trainer["credential_expires_at"] > horizon


def _effective_approval(course_id, jurisdiction_id, start_at):
    for approval in st.rows("course_approvals"):
        if (approval["course_id"] == course_id
                and approval["state_jurisdiction_id"] == jurisdiction_id
                and approval["approval_status"] == "APPROVED"
                and approval["effective_from"] is not None
                and approval["expires_at"] is not None
                and approval["effective_from"] <= start_at < approval["expires_at"]):
            return approval
    return None


@bp.post("/class-sessions")
def create_session():
    caller = authenticate((TRAINER, PROGRAM_ADMIN))
    body = v.body()
    course_id = v.req_str(body, "course_id", 1, None)
    jurisdiction_id = v.req_str(body, "state_jurisdiction_id", 1, None)
    trainer_id = v.req_str(body, "trainer_id", 1, None)
    start_at = v.req_dt(body, "scheduled_start_at")
    end_at = v.req_dt(body, "scheduled_end_at")
    capacity = v.req_int(body, "capacity", 1, 40)
    if end_at <= start_at:
        invalid("Field 'scheduled_end_at' must be strictly after 'scheduled_start_at'.")

    course = v.must_exist("courses", course_id)                        # priority 6
    jurisdiction = v.must_exist("state_jurisdictions", jurisdiction_id)
    trainer = v.must_exist("trainers", trainer_id)

    approval = _effective_approval(course_id, jurisdiction_id, start_at)
    if approval is None:                                               # priority 18
        fail("ERR_APPROVAL_NOT_EFFECTIVE",
             "No APPROVED course approval covers the requested session window.")
    if approval["pinned_course_version"] != course["version"]:         # priority 19
        fail("ERR_APPROVAL_STALE_CONTENT",
             "The approval was pinned to course version %s but the course is at %s."
             % (approval["pinned_course_version"], course["version"]))
    if not _trainer_qualified(trainer, course["track"],
                              jurisdiction["state_code"], end_at):     # priority 20
        fail("ERR_TRAINER_NOT_CERTIFIED",
             "The instructing trainer is not credentialed for this class.")

    buffer_start = start_at - _minutes(BUFFER_MINUTES)
    buffer_end = end_at + _minutes(BUFFER_MINUTES)
    for other in st.rows("class_sessions"):                            # priority 32
        if other["trainer_id"] != trainer_id:
            continue
        if other["session_status"] not in LIVE_SESSION_STATES:
            continue
        if (buffer_start <= other["scheduled_end_at"]
                and other["scheduled_start_at"] <= buffer_end):
            fail("ERR_TRAINER_SCHEDULE_CONFLICT",
                 "The buffered window intersects another live session of this trainer.")

    if start_at <= store.clock:                                        # priority 36
        fail("ERR_SESSION_WINDOW_IN_PAST",
             "scheduled_start_at must be after the current time.")

    row = create_row("class_sessions", {
        "course_id": course_id,
        "state_jurisdiction_id": jurisdiction_id,
        "trainer_id": trainer_id,
        "proctor_trainer_id": None,
        "pinned_course_approval_id": approval["id"],
        "pinned_course_version": course["version"],
        "scheduled_start_at": start_at,
        "scheduled_end_at": end_at,
        "capacity": capacity,
        "enrolled_count": 0,
        "passed_count": 0,
        "session_status": "SCHEDULED",
        "exam_opened_at": None,
        "completed_at": None,
        "cancellation_reason": None,
    })
    return envelope.ok_row(row, 201)


def _minutes(count):
    from datetime import timedelta
    return timedelta(minutes=count)


@bp.post("/class-sessions/<session_id>/lock-roster")
def lock_roster(session_id):
    caller = authenticate((TRAINER, PROGRAM_ADMIN))
    v.body()
    session = v.must_exist("class_sessions", session_id)
    own_session(caller, session)
    if session["session_status"] != "SCHEDULED":                       # priority 13
        fail("ERR_SESSION_INVALID_STATE",
             "Only a SCHEDULED session may be locked; this one is '%s'."
             % session["session_status"])
    if session["enrolled_count"] < 1:                                  # priority 29
        fail("ERR_EMPTY_ROSTER", "The roster has no live enrollment.")
    apply_changes(session, {"session_status": "ROSTER_LOCKED"})
    return envelope.ok_row(session)


@bp.post("/class-sessions/<session_id>/open-exam")
def open_exam(session_id):
    caller = authenticate((TRAINER, PROGRAM_ADMIN))
    body = v.body()
    proctor_id = v.req_str(body, "proctor_trainer_id", 1, None)
    session = v.must_exist("class_sessions", session_id)
    own_session(caller, session)
    proctor = v.must_exist("trainers", proctor_id)                     # priority 6
    if session["session_status"] != "ROSTER_LOCKED":                   # priority 13
        fail("ERR_SESSION_INVALID_STATE",
             "Only a ROSTER_LOCKED session may open its exam; this one is '%s'."
             % session["session_status"])
    approval = st.get("course_approvals", session["pinned_course_approval_id"])
    if approval is None or approval["approval_status"] not in ("APPROVED", "STALE"):
        fail("ERR_APPROVAL_NOT_EFFECTIVE",                             # priority 18
             "The pinned course approval is no longer APPROVED.")
    # PRD 3.2: a session pinned to an approval that a content revision left STALE
    # fails at exam-opening time with ERR_APPROVAL_STALE_CONTENT.
    if (approval["approval_status"] == "STALE"
            or approval["pinned_course_version"] != session["pinned_course_version"]):
        fail("ERR_APPROVAL_STALE_CONTENT",                             # priority 19
             "The course content changed after the pinned approval.")
    course = st.get("courses", session["course_id"])
    jurisdiction = st.get("state_jurisdictions", session["state_jurisdiction_id"])
    if not _trainer_qualified(proctor, course["track"],
                              jurisdiction["state_code"], store.clock):
        fail("ERR_TRAINER_NOT_CERTIFIED",                              # priority 20
             "The nominated proctor is not credentialed for this exam.")
    if (jurisdiction["proctor_separation_required"]
            and proctor_id == session["trainer_id"]):                  # priority 21
        fail("ERR_PROCTOR_SEPARATION_REQUIRED",
             "This jurisdiction requires a proctor other than the instructor.")
    roster = domain.enrollments_of_session(session["id"])
    for enrollment in roster:                                          # priority 30
        if enrollment["enrollment_state"] == "REGISTERED":
            fail("ERR_ATTENDANCE_INCOMPLETE",
                 "At least one enrollment is still REGISTERED.")
    if store.clock < session["scheduled_start_at"]:                    # priority 35
        fail("ERR_EXAM_WINDOW_NOT_OPEN",
             "The exam window opens at scheduled_start_at.")

    apply_changes(session, {
        "proctor_trainer_id": proctor_id,
        "exam_opened_at": store.clock,
        "session_status": "EXAM_OPEN",
    })
    for enrollment in roster:
        if enrollment["enrollment_state"] == "ATTENDED":
            apply_changes(enrollment, {"enrollment_state": "EXAM_SCHEDULED"})
    return envelope.ok_row(session)


@bp.post("/class-sessions/<session_id>/complete")
def complete_session(session_id):
    caller = authenticate((TRAINER, PROGRAM_ADMIN))
    v.body()
    session = v.must_exist("class_sessions", session_id)
    own_session(caller, session)
    if session["session_status"] != "EXAM_OPEN":                       # priority 13
        fail("ERR_SESSION_INVALID_STATE",
             "Only an EXAM_OPEN session may be completed; this one is '%s'."
             % session["session_status"])
    for enrollment in domain.enrollments_of_session(session["id"]):    # priority 14
        if enrollment["enrollment_state"] == "EXAM_IN_PROGRESS":
            fail("ERR_ENROLLMENT_INVALID_STATE",
                 "An exam attempt is still in progress on this roster.")
    domain.complete_session(session)
    return envelope.ok_row(session)


@bp.post("/class-sessions/<session_id>/cancel")
def cancel_session(session_id):
    caller = authenticate((TRAINER, PROGRAM_ADMIN))
    body = v.body()
    cancellation_reason = v.req_str(body, "cancellation_reason", 1, None)
    session = v.must_exist("class_sessions", session_id)
    own_session(caller, session)
    if session["session_status"] not in domain.CANCELLABLE_SESSION_STATES:
        fail("ERR_SESSION_INVALID_STATE",                              # priority 13
             "A session in '%s' cannot be cancelled." % session["session_status"])
    domain.cancel_session(session, cancellation_reason, "SESSION_CANCELLED")
    return envelope.ok_row(session)


@bp.get("/class-sessions/<session_id>")
def read_session(session_id):
    authenticate((PROGRAM_ADMIN, STATE_REGULATOR, TRAINER, EMPLOYER_ADMIN))
    return envelope.ok_row(v.must_exist("class_sessions", session_id))


@bp.get("/class-sessions")
def list_sessions():
    authenticate((PROGRAM_ADMIN, STATE_REGULATOR, TRAINER, EMPLOYER_ADMIN))
    filters = {
        "course_id": v.q_str("course_id"),
        "state_jurisdiction_id": v.q_str("state_jurisdiction_id"),
        "trainer_id": v.q_str("trainer_id"),
        "proctor_trainer_id": v.q_str("proctor_trainer_id"),
        "pinned_course_approval_id": v.q_str("pinned_course_approval_id"),
        "session_status": v.q_enum("session_status", v.SESSION_STATUSES),
    }

    def keep(row):
        for key, wanted in filters.items():
            if wanted is not None and row[key] != wanted:
                return False
        return True

    return paged([r for r in st.rows("class_sessions") if keep(r)])


# --- alcohol servers -------------------------------------------------------

@bp.post("/alcohol-servers")
def create_server():
    authenticate((PROGRAM_ADMIN, EMPLOYER_ADMIN))
    body = v.body()
    full_name = v.req_str(body, "full_name", 1, 120)
    email = v.req_email(body, "email")
    jurisdiction_id = v.req_str(body, "state_jurisdiction_id", 1, None)
    v.must_exist("state_jurisdictions", jurisdiction_id)               # priority 6
    for row in st.rows("alcohol_servers"):                             # priority 24
        if row["email"] == email:
            fail("ERR_IDENTITY_ALREADY_REGISTERED",
                 "email '%s' is already registered." % email)
    row = create_row("alcohol_servers", {
        "full_name": full_name,
        "email": email,
        "state_jurisdiction_id": jurisdiction_id,
        "active_certificate_id": None,
        "work_eligibility": "UNCERTIFIED",
        "certification_count": 0,
        "restricted_since": None,
    })
    return envelope.ok_row(row, 201)


@bp.get("/alcohol-servers/<server_id>")
def read_server(server_id):
    authenticate((PROGRAM_ADMIN, STATE_REGULATOR, TRAINER, EMPLOYER_ADMIN,
                  ALCOHOL_SERVER))
    return envelope.ok_row(v.must_exist("alcohol_servers", server_id))


@bp.get("/alcohol-servers")
def list_servers():
    authenticate((PROGRAM_ADMIN, STATE_REGULATOR, EMPLOYER_ADMIN))
    jurisdiction_id = v.q_str("state_jurisdiction_id")
    eligibility = v.q_enum("work_eligibility", v.WORK_ELIGIBILITIES)
    certificate_id = v.q_str("active_certificate_id")

    def keep(row):
        if (jurisdiction_id is not None
                and row["state_jurisdiction_id"] != jurisdiction_id):
            return False
        if eligibility is not None and row["work_eligibility"] != eligibility:
            return False
        if certificate_id is not None and row["active_certificate_id"] != certificate_id:
            return False
        return True

    return paged([r for r in st.rows("alcohol_servers") if keep(r)])


@bp.get("/alcohol-servers/<server_id>/server-assignments")
def list_server_assignments(server_id):
    caller = authenticate((PROGRAM_ADMIN, EMPLOYER_ADMIN, ALCOHOL_SERVER))
    limit, offset = v.pagination()
    server = v.must_exist("alcohol_servers", server_id)
    if caller.is_alcohol_server and caller.user_id != server["id"]:
        deny_ownership()
    items = [
        a for a in st.rows("server_assignments")
        if a["alcohol_server_id"] == server["id"]
    ]
    page, total = envelope.paginate(items, limit, offset)
    return envelope.ok_list(page, limit, offset, total)


# --- enrollments -----------------------------------------------------------

@bp.post("/enrollments")
def create_enrollment():
    caller = authenticate((EMPLOYER_ADMIN, ALCOHOL_SERVER, PROGRAM_ADMIN))
    body = v.body()
    session_id = v.req_str(body, "class_session_id", 1, None)
    server_id = v.req_str(body, "alcohol_server_id", 1, None)
    expected_version = v.req_int(body, "expected_class_session_version")
    account_id = v.opt_str(body, "sponsoring_employer_account_id", 1, None)

    if caller.is_alcohol_server and caller.user_id != server_id:       # priority 5
        deny_ownership()
    if caller.is_employer_admin and account_id is not None \
            and caller.user_id != account_id:
        deny_ownership()

    session = v.must_exist("class_sessions", session_id)               # priority 6
    server = v.must_exist("alcohol_servers", server_id)
    account = None
    if account_id is not None:
        account = v.must_exist("employer_accounts", account_id)

    if expected_version != session["version"]:                         # priority 7
        fail("ERR_STALE_SESSION_VERSION",
             "expected_class_session_version %s does not match the session version %s."
             % (expected_version, session["version"]))
    if session["session_status"] != "SCHEDULED":                        # priority 13
        fail("ERR_SESSION_INVALID_STATE",
             "Only a SCHEDULED session accepts enrollments; this one is '%s'."
             % session["session_status"])
    if account is not None and account["account_status"] == "SUSPENDED":  # priority 17
        fail("ERR_ACCOUNT_INVALID_STATE",
             "A SUSPENDED employer account cannot sponsor a seat.")
    for enrollment in domain.enrollments_of_session(session["id"]):     # priority 26
        if (enrollment["alcohol_server_id"] == server_id
                and enrollment["enrollment_state"] != "WITHDRAWN"):
            fail("ERR_DUPLICATE_ENROLLMENT",
                 "The server already holds a live enrollment on this session.")
    if session["enrolled_count"] >= session["capacity"]:                # priority 28
        fail("ERR_SESSION_AT_CAPACITY", "The session has reached its capacity.")

    for other in st.rows("enrollments"):                               # priority 33
        if other["alcohol_server_id"] != server_id:
            continue
        if other["enrollment_state"] not in domain.LIVE_ENROLLMENT_STATES_FOR_OVERLAP:
            continue
        other_session = st.get("class_sessions", other["class_session_id"])
        if other_session is None or other_session["id"] == session["id"]:
            continue
        if (session["scheduled_start_at"] < other_session["scheduled_end_at"]
                and other_session["scheduled_start_at"] < session["scheduled_end_at"]):
            fail("ERR_SERVER_SESSION_OVERLAP",
                 "The session window overlaps another session of this server.")

    if account is not None and account["seat_credit_balance"] < 1:     # priority 37
        fail("ERR_INSUFFICIENT_SEAT_CREDITS",
             "The sponsoring account has no seat credit available.")

    row = create_row("enrollments", {
        "class_session_id": session["id"],
        "alcohol_server_id": server["id"],
        "sponsoring_employer_account_id": account["id"] if account else None,
        "enrollment_state": "REGISTERED",
        "paid_by": "EMPLOYER_CREDIT" if account else "SELF_PAY",
        "seat_credit_charged": bool(account),
        "attempt_count": 0,
        "best_score_pct": None,
        "last_counted_attempt_ended_at": None,
        "retake_eligible_at": None,
        "withdrawal_reason": None,
    })
    if account is not None:
        domain.consume_seat_credit(account)
    apply_changes(session, {
        "enrolled_count": domain.live_enrolled_count(session["id"]),
    })
    return envelope.ok_row(row, 201)


@bp.post("/enrollments/<enrollment_id>/attendance")
def mark_attendance(enrollment_id):
    caller = authenticate((TRAINER, PROGRAM_ADMIN))
    body = v.body()
    attended = v.req_bool(body, "attended")
    enrollment = v.must_exist("enrollments", enrollment_id)
    session = st.get("class_sessions", enrollment["class_session_id"])
    own_session(caller, session)                                       # priority 5
    if session["session_status"] != "ROSTER_LOCKED":                   # priority 13
        fail("ERR_SESSION_INVALID_STATE",
             "Attendance requires a ROSTER_LOCKED session; this one is '%s'."
             % session["session_status"])
    if enrollment["enrollment_state"] != "REGISTERED":                 # priority 14
        fail("ERR_ENROLLMENT_INVALID_STATE",
             "Only a REGISTERED seat may be marked; this one is '%s'."
             % enrollment["enrollment_state"])
    apply_changes(enrollment, {
        "enrollment_state": "ATTENDED" if attended else "NO_SHOW",
    })
    return envelope.ok_row(enrollment)


@bp.post("/enrollments/<enrollment_id>/withdraw")
def withdraw_enrollment(enrollment_id):
    caller = authenticate((EMPLOYER_ADMIN, ALCOHOL_SERVER, PROGRAM_ADMIN))
    body = v.body()
    withdrawal_reason = v.opt_str(body, "withdrawal_reason", 1, None)
    enrollment = v.must_exist("enrollments", enrollment_id)
    if caller.is_employer_admin:                                       # priority 5
        if caller.user_id != enrollment["sponsoring_employer_account_id"]:
            deny_ownership()
    if caller.is_alcohol_server and caller.user_id != enrollment["alcohol_server_id"]:
        deny_ownership()
    session = st.get("class_sessions", enrollment["class_session_id"])
    if session["session_status"] not in domain.CANCELLABLE_SESSION_STATES:
        fail("ERR_SESSION_INVALID_STATE",                              # priority 13
             "A seat on a '%s' session cannot be withdrawn."
             % session["session_status"])
    if enrollment["enrollment_state"] not in ("REGISTERED", "ATTENDED", "NO_SHOW"):
        fail("ERR_ENROLLMENT_INVALID_STATE",                           # priority 14
             "A seat in '%s' cannot be withdrawn." % enrollment["enrollment_state"])
    changes = {"enrollment_state": "WITHDRAWN"}
    if withdrawal_reason is not None:
        changes["withdrawal_reason"] = withdrawal_reason
    apply_changes(enrollment, changes)
    domain.refund_seat_credit(enrollment)
    apply_changes(session, {
        "enrolled_count": domain.live_enrolled_count(session["id"]),
    })
    return envelope.ok_row(enrollment)


@bp.post("/enrollments/<enrollment_id>/exam-attempts")
def open_attempt(enrollment_id):
    caller = authenticate((TRAINER,))
    v.body()
    enrollment = v.must_exist("enrollments", enrollment_id)
    session = st.get("class_sessions", enrollment["class_session_id"])
    own_proctor(caller, session)                                       # priority 5
    if session["session_status"] != "EXAM_OPEN":                       # priority 13
        fail("ERR_SESSION_INVALID_STATE",
             "Exam attempts require an EXAM_OPEN session; this one is '%s'."
             % session["session_status"])
    if enrollment["enrollment_state"] not in ("EXAM_SCHEDULED", "EXAM_FAILED"):
        fail("ERR_ENROLLMENT_INVALID_STATE",                           # priority 14
             "A seat in '%s' cannot start an attempt."
             % enrollment["enrollment_state"])
    jurisdiction = st.get("state_jurisdictions", session["state_jurisdiction_id"])
    if enrollment["attempt_count"] >= 1 + jurisdiction["max_retakes_allowed"]:
        fail("ERR_RETAKE_LIMIT_EXCEEDED",                              # priority 31
             "The retake limit for this jurisdiction is exhausted.")
    if (enrollment["retake_eligible_at"] is not None
            and store.clock < enrollment["retake_eligible_at"]):       # priority 34
        fail("ERR_RETAKE_COOLING_OFF", "The cooling-off window has not elapsed.")

    course = st.get("courses", session["course_id"])
    attempt = create_row("exam_attempts", {
        "enrollment_id": enrollment["id"],
        "attempt_number": enrollment["attempt_count"] + 1,
        "question_count": course["question_count"],
        "raw_correct_count": None,
        "score_pct": None,
        "outcome": "IN_PROGRESS",
        "proctor_attestation": None,
        "started_at": store.clock,
        "submitted_at": None,
        "void_reason": None,
    })
    apply_changes(enrollment, {"enrollment_state": "EXAM_IN_PROGRESS"})
    return envelope.ok_row(attempt, 201)


@bp.post("/exam-attempts/<attempt_id>/submit")
def submit_attempt(attempt_id):
    caller = authenticate((TRAINER,))
    body = v.body()
    raw_correct_count = v.req_int(body, "raw_correct_count", 0, None)
    attestation = v.req_bool(body, "proctor_attestation")
    attempt = v.must_exist("exam_attempts", attempt_id)
    if raw_correct_count > attempt["question_count"]:
        invalid("Field 'raw_correct_count' exceeds the attempt's question count.")
    enrollment = st.get("enrollments", attempt["enrollment_id"])
    session = st.get("class_sessions", enrollment["class_session_id"])
    own_proctor(caller, session)                                       # priority 5
    if attempt["outcome"] != "IN_PROGRESS":                            # priority 14
        fail("ERR_ENROLLMENT_INVALID_STATE",
             "The attempt is no longer IN_PROGRESS; it is '%s'." % attempt["outcome"])

    jurisdiction = st.get("state_jurisdictions", session["state_jurisdiction_id"])
    pct = score_pct(raw_correct_count, attempt["question_count"])
    changes = {
        "raw_correct_count": raw_correct_count,
        "proctor_attestation": attestation,
        "score_pct": pct,
        "submitted_at": store.clock,
    }
    if not attestation:
        changes["outcome"] = "VOIDED"
        changes["void_reason"] = "PROCTOR_ATTESTATION_WITHHELD"
        apply_changes(attempt, changes)
        apply_changes(enrollment, {"enrollment_state": "EXAM_SCHEDULED"})
        return envelope.ok_row(attempt)

    passed = pct >= jurisdiction["min_passing_score_pct"]
    changes["outcome"] = "PASS" if passed else "FAIL"
    apply_changes(attempt, changes)

    counters = domain.recompute_attempt_counters(enrollment, jurisdiction)
    counters["enrollment_state"] = "PASSED" if passed else "EXAM_FAILED"
    apply_changes(enrollment, counters)
    if passed:
        apply_changes(session, {
            "passed_count": len([
                e for e in domain.enrollments_of_session(session["id"])
                if e["enrollment_state"] == "PASSED"
            ]),
        })
    return envelope.ok_row(attempt)


@bp.get("/enrollments/<enrollment_id>")
def read_enrollment(enrollment_id):
    authenticate((PROGRAM_ADMIN, TRAINER, EMPLOYER_ADMIN, ALCOHOL_SERVER))
    return envelope.ok_row(v.must_exist("enrollments", enrollment_id))


@bp.get("/enrollments")
def list_enrollments():
    authenticate((PROGRAM_ADMIN, TRAINER, EMPLOYER_ADMIN, ALCOHOL_SERVER))
    filters = {
        "class_session_id": v.q_str("class_session_id"),
        "alcohol_server_id": v.q_str("alcohol_server_id"),
        "sponsoring_employer_account_id": v.q_str("sponsoring_employer_account_id"),
        "enrollment_state": v.q_enum("enrollment_state", v.ENROLLMENT_STATES),
    }

    def keep(row):
        for key, wanted in filters.items():
            if wanted is not None and row[key] != wanted:
                return False
        return True

    return paged([r for r in st.rows("enrollments") if keep(r)])


@bp.get("/enrollments/<enrollment_id>/exam-attempts")
def list_attempts(enrollment_id):
    authenticate((PROGRAM_ADMIN, STATE_REGULATOR, TRAINER, ALCOHOL_SERVER))
    limit, offset = v.pagination()
    enrollment = v.must_exist("enrollments", enrollment_id)
    items = domain.attempts_of_enrollment(enrollment["id"])
    page, total = envelope.paginate(items, limit, offset)
    return envelope.ok_list(page, limit, offset, total)
