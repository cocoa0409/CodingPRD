from datetime import timedelta

from flask import Blueprint

import store
from errors import ApiError
import context as ctx
from serializers import public, public_list
import envelope as env

bp = Blueprint("education", __name__)

CERT_VALIDITY_DAYS = 365
SESSION_BUFFER = timedelta(minutes=30)


# ---- Education sessions ------------------------------------------------------
@bp.post("/education-sessions")
def create_session():
    ctx.authenticate(["ProgramAdmin"])
    data = ctx.body()
    program_id = data.get("program_id")
    if program_id is not None:
        ctx.lookup("program", program_id)
    program_id = ctx.req_str(data, "program_id")
    title = ctx.req_str(data, "title")
    start_raw, start_dt = ctx.req_datetime(data, "start_at")
    end_raw, end_dt = ctx.req_datetime(data, "end_at")
    capacity = ctx.req_int(data, "capacity", 1)
    if not (end_dt > start_dt):
        raise ApiError("ERR_SESSION_TIME_INVALID", "end_at must be strictly after start_at.")

    rec = store.new_record("session")
    rec.update({
        "program_id": program_id,
        "title": title,
        "start_at": start_raw,
        "end_at": end_raw,
        "capacity": capacity,
        "enrolled_count": 0,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
    })
    store.sessions[rec["id"]] = rec
    return env.success(public(rec), 201)


@bp.get("/education-sessions/<sid>")
def get_session(sid):
    ctx.authenticate(["ProgramAdmin", "CaseManager", "Applicant"])
    rec = ctx.lookup("session", sid)
    return env.success(public(rec), 200)


def _intervals_conflict(a_start, a_end, b_start, b_end):
    return (b_start < a_end + SESSION_BUFFER) and (a_start < b_end + SESSION_BUFFER)


@bp.post("/education-sessions/<sid>/enrollments")
def enroll(sid):
    ctx.authenticate(["Applicant"])
    session = ctx.lookup("session", sid)
    data = ctx.body()
    applicant_id = data.get("applicant_id")
    if applicant_id is not None:
        ctx.lookup("applicant", applicant_id)
    applicant_id = ctx.req_str(data, "applicant_id")

    # Priority 13: scheduling conflict with the applicant's active enrollments.
    for en in store.enrollments.values():
        if en["applicant_id"] != applicant_id:
            continue
        if en["status"] not in ("ENROLLED", "ATTENDED"):
            continue
        other = store.sessions.get(en["session_id"])
        if other is None:
            continue
        if _intervals_conflict(session["_start_dt"], session["_end_dt"],
                               other["_start_dt"], other["_end_dt"]):
            raise ApiError("ERR_SESSION_TIME_CONFLICT",
                           "Applicant already enrolled in a conflicting session.")

    # Priority 14: capacity.
    if session["enrolled_count"] >= session["capacity"]:
        raise ApiError("ERR_SESSION_FULL", "Education session is at capacity.")

    rec = store.new_record("enrollment")
    rec.update({
        "session_id": sid,
        "applicant_id": applicant_id,
        "status": "ENROLLED",
    })
    store.enrollments[rec["id"]] = rec
    session["enrolled_count"] += 1
    store.touch(session)
    return env.success(public(rec), 201)


@bp.get("/education-sessions/<sid>/enrollments")
def list_session_enrollments(sid):
    ctx.authenticate(["ProgramAdmin", "CaseManager"])
    ctx.lookup("session", sid)
    limit, offset = ctx.pagination_params()
    rows = [e for e in store.enrollments.values() if e["session_id"] == sid]
    page, total = ctx.paginate(rows, limit, offset)
    return env.list_response(public_list(page), limit, offset, total)


# ---- Enrollments -------------------------------------------------------------
@bp.get("/enrollments/<eid>")
def get_enrollment(eid):
    ctx.authenticate(["ProgramAdmin", "CaseManager", "Applicant"])
    rec = ctx.lookup("enrollment", eid)
    return env.success(public(rec), 200)


@bp.get("/enrollments")
def list_enrollments():
    ctx.authenticate(["ProgramAdmin", "CaseManager"])
    limit, offset = ctx.pagination_params()
    filters = {
        "session_id": ctx.query_filter("session_id"),
        "applicant_id": ctx.query_filter("applicant_id"),
        "status": ctx.query_filter("status"),
    }
    page, total = ctx.paginate(store.enrollments.values(), limit, offset, filters)
    return env.list_response(public_list(page), limit, offset, total)


@bp.post("/enrollments/<eid>/attend")
def attend(eid):
    ctx.authenticate(["ProgramAdmin"])
    en = ctx.lookup("enrollment", eid)
    if en["status"] != "ENROLLED":
        raise ApiError("ERR_INVALID_STATE", "Enrollment is not ENROLLED.")
    session = store.sessions[en["session_id"]]
    if store.clock_now() < session["_start_dt"]:
        raise ApiError("ERR_INVALID_STATE", "Session has not started yet.")
    en["status"] = "ATTENDED"
    store.touch(en)

    # CASCADE: mint the education certificate.
    issued = store.clock_now()
    expires = issued + timedelta(days=CERT_VALIDITY_DAYS)
    cert = store.new_record("certificate")
    cert.update({
        "applicant_id": en["applicant_id"],
        "source_enrollment_id": en["id"],
        "issued_at": store.format_ts(issued),
        "expires_at": store.format_ts(expires),
        "status": "VALID",
        "_expires_dt": expires,
    })
    store.certificates[cert["id"]] = cert
    return env.success(public(en), 200)


@bp.post("/enrollments/<eid>/no-show")
def no_show(eid):
    ctx.authenticate(["ProgramAdmin"])
    en = ctx.lookup("enrollment", eid)
    if en["status"] != "ENROLLED":
        raise ApiError("ERR_INVALID_STATE", "Enrollment is not ENROLLED.")
    en["status"] = "NO_SHOW"
    store.touch(en)
    session = store.sessions[en["session_id"]]
    session["enrolled_count"] -= 1
    store.touch(session)
    return env.success(public(en), 200)


@bp.post("/enrollments/<eid>/cancel")
def cancel_enrollment(eid):
    ctx.authenticate(["Applicant"])
    en = ctx.lookup("enrollment", eid)
    if en["status"] != "ENROLLED":
        raise ApiError("ERR_INVALID_STATE", "Enrollment is not ENROLLED.")
    en["status"] = "CANCELLED"
    store.touch(en)
    session = store.sessions[en["session_id"]]
    session["enrolled_count"] -= 1
    store.touch(session)
    return env.success(public(en), 200)


# ---- Certificates ------------------------------------------------------------
@bp.get("/certificates/<cid>")
def get_certificate(cid):
    ctx.authenticate(["ProgramAdmin", "CaseManager", "Applicant"])
    rec = ctx.lookup("certificate", cid)
    return env.success(public(rec), 200)


@bp.get("/certificates")
def list_certificates():
    ctx.authenticate(["ProgramAdmin", "CaseManager"])
    limit, offset = ctx.pagination_params()
    status_f = ctx.query_filter("status")
    rows = list(store.certificates.values())
    ap = ctx.query_filter("applicant_id")
    se = ctx.query_filter("source_enrollment_id")
    if ap is not None:
        rows = [r for r in rows if r["applicant_id"] == ap]
    if se is not None:
        rows = [r for r in rows if r["source_enrollment_id"] == se]
    if status_f is not None:
        rows = [r for r in rows
                if ("VALID" if store.clock_now() <= r["_expires_dt"] else "EXPIRED") == status_f]
    page, total = ctx.paginate(rows, limit, offset)
    return env.list_response(public_list(page), limit, offset, total)
