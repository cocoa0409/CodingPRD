from datetime import timedelta

from flask import Blueprint, request as flask_request

from db import db
from errors import err
from clock import parse_iso
from middleware import authenticate, require_role
from response import ok, ok_list
from helpers import get_body, paginate, sort_by_created, require_fields, check_enum
from services import constants as C
from services import calc
from services import engine

bp = Blueprint("sessions", __name__)


def _assignment_of(session):
    return db.assignments.get(session["assignment_id"])


def _request_of(session):
    a = _assignment_of(session)
    if not a:
        return None
    return db.requests.get(a["request_id"])


def _interpreter_of(session):
    a = _assignment_of(session)
    if not a:
        return None
    return db.interpreters.get(a["interpreter_id"])


def _client_owns_session(uid, session):
    req = _request_of(session)
    return req is not None and req["client_id"] == uid


def _interp_owns_session(uid, session):
    a = _assignment_of(session)
    return a is not None and a["interpreter_id"] == uid


def _effective_plan_or_error(req):
    plan = calc.find_active_rate_plan(req["client_id"], req["required_tier"], req["modality"])
    if plan is None:
        raise err("ERR_NO_RATE_PLAN", "No active rate plan for this request")
    return plan


def _session_swept_into_issued_invoice(session):
    a = _assignment_of(session)
    return a is not None and a["billing_status"] == "INVOICED"


# ===================== Fetch / list =====================

@bp.get("/interpretation/sessions/<sid>")
def get_session(sid):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "CoordinatorOps", "Interpreter", "ClientAccount"})
    s = db.sessions.get(sid)
    if not s:
        raise err("ERR_RESOURCE_NOT_FOUND", "Session not found")
    return ok(s)


@bp.get("/interpretation/sessions")
def list_sessions():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "CoordinatorOps", "Interpreter", "ClientAccount"})
    rows = list(db.sessions.values())
    aid = flask_request.args.get("assignment_id")
    status = flask_request.args.get("status")
    if aid is not None:
        rows = [r for r in rows if r["assignment_id"] == aid]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_by_created(rows)
    window, limit, offset, total = paginate(rows)
    return ok_list(window, limit, offset, total)


# ===================== Connect =====================

@bp.post("/interpretation/sessions/<sid>/connect")
def connect_session(sid):
    uid, role = authenticate()
    require_role(role, {"Interpreter"})
    s = db.sessions.get(sid)
    if not s:
        raise err("ERR_RESOURCE_NOT_FOUND", "Session not found")
    if s["status"] != "CONNECTING":
        raise err("ERR_INVALID_STATE", "Session is not CONNECTING")
    if not _interp_owns_session(uid, s):
        raise err("ERR_NOT_OWNER", "Interpreter does not own this session")
    s["connected_at"] = db.clock.now_iso()
    s["status"] = "ACTIVE"
    db.touch(s)
    return ok(s)


# ===================== End =====================

@bp.post("/interpretation/sessions/<sid>/end")
def end_session(sid):
    uid, role = authenticate()
    require_role(role, {"Interpreter"})
    s = db.sessions.get(sid)
    if not s:
        raise err("ERR_RESOURCE_NOT_FOUND", "Session not found")
    if s["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Session is not ACTIVE")
    if not _interp_owns_session(uid, s):
        raise err("ERR_NOT_OWNER", "Interpreter does not own this session")
    req = _request_of(s)
    plan = _effective_plan_or_error(req)
    s["ended_at"] = db.clock.now_iso()
    duration = (parse_iso(s["ended_at"]) - parse_iso(s["connected_at"])).total_seconds()
    units, amount = calc.session_billing(plan, req["modality"], duration)
    s["billed_units"] = units
    s["billed_amount_cents"] = amount
    s["status"] = "ENDED"
    db.touch(s)
    a = _assignment_of(s)
    engine.complete_assignment(a, "BILLABLE")
    return ok(s)


# ===================== Mark no-show =====================

@bp.post("/interpretation/sessions/<sid>/mark-no-show")
def mark_no_show(sid):
    _, role = authenticate()
    require_role(role, {"CoordinatorOps"})
    s = db.sessions.get(sid)
    if not s:
        raise err("ERR_RESOURCE_NOT_FOUND", "Session not found")
    body = get_body()
    require_fields(body, ["party"])
    party = body["party"]
    if party not in ("CLIENT", "INTERPRETER"):
        raise err("ERR_INVALID_NO_SHOW_PARTY", "party must be CLIENT or INTERPRETER")
    if s["status"] != "CONNECTING":
        raise err("ERR_INVALID_STATE", "Session is not CONNECTING")
    req = _request_of(s)
    a = _assignment_of(s)
    # grace check: clock >= start instant + NO_SHOW_GRACE_SECONDS
    if req["scheduling_mode"] == "SCHEDULED" and req.get("window_start"):
        start_instant = parse_iso(req["window_start"])
    else:
        # ON_DEMAND: offer-accept moment
        start_instant = parse_iso(a["_accepted_at"])
    grace_deadline = start_instant + timedelta(seconds=C.NO_SHOW_GRACE_SECONDS)
    if db.clock.now() < grace_deadline:
        raise err("ERR_INVALID_STATE", "No-show grace window has not elapsed")

    if party == "CLIENT":
        plan = _effective_plan_or_error(req)
        fee = calc.no_show_fee(plan, req["modality"])
        req["cancellation_fee_cents"] = fee
        db.touch(req)
        s["status"] = "CLIENT_NO_SHOW"
        db.touch(s)
        engine.complete_assignment(a, "BILLABLE")
    else:  # INTERPRETER
        s["status"] = "INTERPRETER_NO_SHOW"
        db.touch(s)
        interp = db.interpreters.get(a["interpreter_id"])
        engine.complete_assignment(a, "WAIVED")
        if interp:
            interp["no_show_strikes"] = interp["no_show_strikes"] + 1
            db.touch(interp)
            engine.maybe_deactivate_interpreter(interp)
    return ok(s)


# ===================== Dispute =====================

@bp.post("/interpretation/sessions/<sid>/dispute")
def dispute_session(sid):
    uid, role = authenticate()
    require_role(role, {"ClientAccount"})
    s = db.sessions.get(sid)
    if not s:
        raise err("ERR_RESOURCE_NOT_FOUND", "Session not found")
    if not _client_owns_session(uid, s):
        raise err("ERR_NOT_OWNER", "Client does not own this session")
    if s["status"] != "ENDED":
        raise err("ERR_SESSION_NOT_ENDED", "Session is not ENDED")
    if _session_swept_into_issued_invoice(s):
        raise err("ERR_SESSION_ALREADY_INVOICED", "Session already swept into an issued invoice")
    s["status"] = "DISPUTED"
    db.touch(s)
    return ok(s)


# ===================== Reopen =====================

@bp.post("/interpretation/sessions/<sid>/reopen")
def reopen_session(sid):
    _, role = authenticate()
    require_role(role, {"CoordinatorOps"})
    s = db.sessions.get(sid)
    if not s:
        raise err("ERR_RESOURCE_NOT_FOUND", "Session not found")
    if s["status"] != "DISPUTED":
        raise err("ERR_INVALID_STATE", "Session is not DISPUTED")
    s["ended_at"] = None
    s["status"] = "ACTIVE"
    db.touch(s)
    # re-open the assignment to IN_SESSION so a subsequent end can re-complete
    a = _assignment_of(s)
    if a and a["lifecycle_status"] == "COMPLETED":
        a["lifecycle_status"] = "IN_SESSION"
        db.touch(a)
        interp = db.interpreters.get(a["interpreter_id"])
        if interp:
            engine.recompute_active_load(interp)
            db.touch(interp)
    req = _request_of(s)
    if req and req["status"] == "FULFILLED":
        req["status"] = "ASSIGNED"
        db.touch(req)
    return ok(s)


# ===================== Reconcile =====================

@bp.post("/interpretation/sessions/<sid>/reconcile")
def reconcile_session(sid):
    _, role = authenticate()
    require_role(role, {"CoordinatorOps"})
    s = db.sessions.get(sid)
    if not s:
        raise err("ERR_RESOURCE_NOT_FOUND", "Session not found")
    body = get_body()
    require_fields(body, ["corrected_billed_units"])
    cbu = body["corrected_billed_units"]
    if s["status"] != "DISPUTED":
        raise err("ERR_INVALID_STATE", "Session is not DISPUTED")
    if not isinstance(cbu, int) or isinstance(cbu, bool) or cbu < 0:
        raise err("ERR_INVALID_CORRECTED_UNITS", "corrected_billed_units must be a non-negative integer")
    req = _request_of(s)
    plan = _effective_plan_or_error(req)
    units, amount = calc.reconcile_billing(plan, req["modality"], cbu)
    s["billed_units"] = units
    s["billed_amount_cents"] = amount
    s["status"] = "RECONCILED"
    db.touch(s)
    a = _assignment_of(s)
    if a:
        a["billing_status"] = "BILLABLE"
        if a["lifecycle_status"] != "COMPLETED":
            a["lifecycle_status"] = "COMPLETED"
        db.touch(a)
        interp = db.interpreters.get(a["interpreter_id"])
        if interp:
            was_busy = interp["status"] == "BUSY"
            engine.recompute_active_load(interp)
            if was_busy and interp["active_load"] < interp["max_concurrent_load"]:
                interp["status"] = "AVAILABLE"
            db.touch(interp)
    if req and req["status"] in ("ASSIGNED",):
        req["status"] = "FULFILLED"
        db.touch(req)
    return ok(s)


# ===================== Rating =====================

@bp.post("/interpretation/sessions/<sid>/rating")
def rate_session(sid):
    uid, role = authenticate()
    require_role(role, {"ClientAccount"})
    s = db.sessions.get(sid)
    if not s:
        raise err("ERR_RESOURCE_NOT_FOUND", "Session not found")
    body = get_body()
    require_fields(body, ["score"])
    score = body["score"]
    if not isinstance(score, int) or isinstance(score, bool) or score < 1 or score > 5:
        raise err("ERR_INVALID_REQUEST", "score must be an integer in [1,5]")
    if not _client_owns_session(uid, s):
        raise err("ERR_NOT_OWNER", "Client does not own this session")
    for r in db.ratings.values():
        if r["session_id"] == sid:
            raise err("ERR_ALREADY_RATED", "Session already rated")
    a = _assignment_of(s)
    entity = db.base_fields()
    entity.update({
        "session_id": sid,
        "interpreter_id": a["interpreter_id"] if a else None,
        "score": score,
        "comment": body.get("comment"),
    })
    db.ratings[entity["id"]] = entity
    interp = db.interpreters.get(a["interpreter_id"]) if a else None
    if interp:
        engine.refresh_interpreter_computed(interp)
        db.touch(interp)
    return ok(entity, 201)


@bp.get("/interpretation/sessions/<sid>/ratings")
def list_session_ratings(sid):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "CoordinatorOps", "ClientAccount"})
    s = db.sessions.get(sid)
    if not s:
        raise err("ERR_RESOURCE_NOT_FOUND", "Session not found")
    rows = [r for r in db.ratings.values() if r["session_id"] == sid]
    rows = sort_by_created(rows)
    window, limit, offset, total = paginate(rows)
    return ok_list(window, limit, offset, total)


# ===================== Encounters =====================

@bp.post("/interpretation/sessions/<sid>/encounters")
def file_encounter(sid):
    uid, role = authenticate()
    require_role(role, {"ClientAccount"})
    s = db.sessions.get(sid)
    if not s:
        raise err("ERR_RESOURCE_NOT_FOUND", "Session not found")
    body = get_body()
    require_fields(body, ["subject_ref", "summary"])
    if not _client_owns_session(uid, s):
        raise err("ERR_NOT_OWNER", "Client does not own this session")
    entity = db.base_fields()
    entity.update({
        "session_id": sid,
        "subject_ref": body["subject_ref"],
        "summary": body["summary"],
        "filed_at": db.clock.now_iso(),
    })
    db.encounters[entity["id"]] = entity
    return ok(entity, 201)


@bp.get("/interpretation/sessions/<sid>/encounters")
def list_encounters(sid):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "CoordinatorOps", "ClientAccount"})
    s = db.sessions.get(sid)
    if not s:
        raise err("ERR_RESOURCE_NOT_FOUND", "Session not found")
    rows = [e for e in db.encounters.values() if e["session_id"] == sid]
    rows = sort_by_created(rows)
    window, limit, offset, total = paginate(rows)
    return ok_list(window, limit, offset, total)


# ===================== Ratings top-level =====================

@bp.get("/interpretation/ratings/<rid>")
def get_rating(rid):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "CoordinatorOps"})
    r = db.ratings.get(rid)
    if not r:
        raise err("ERR_RESOURCE_NOT_FOUND", "Rating not found")
    return ok(r)


@bp.get("/interpretation/ratings")
def list_ratings():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "CoordinatorOps"})
    rows = list(db.ratings.values())
    iid = flask_request.args.get("interpreter_id")
    sid = flask_request.args.get("session_id")
    if iid is not None:
        rows = [r for r in rows if r["interpreter_id"] == iid]
    if sid is not None:
        rows = [r for r in rows if r["session_id"] == sid]
    rows = sort_by_created(rows)
    window, limit, offset, total = paginate(rows)
    return ok_list(window, limit, offset, total)
