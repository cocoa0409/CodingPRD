from datetime import timedelta

from flask import Blueprint, request as flask_request

from db import db
from errors import err
from clock import parse_iso
from middleware import authenticate, require_role
from response import ok, ok_list
from helpers import get_body, paginate, sort_by_created
from services import constants as C
from services import engine
from services import calc

bp = Blueprint("assignments", __name__)


@bp.get("/interpretation/assignments/<aid>")
def get_assignment(aid):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "CoordinatorOps", "Interpreter"})
    engine.sweep_expired_offers()
    a = db.assignments.get(aid)
    if not a:
        raise err("ERR_RESOURCE_NOT_FOUND", "Assignment not found")
    return ok(a)


@bp.get("/interpretation/assignments")
def list_assignments():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "CoordinatorOps", "Interpreter"})
    engine.sweep_expired_offers()
    rows = list(db.assignments.values())
    req_id = flask_request.args.get("request_id")
    interp_id = flask_request.args.get("interpreter_id")
    lifecycle = flask_request.args.get("lifecycle_status")
    if req_id is not None:
        rows = [r for r in rows if r["request_id"] == req_id]
    if interp_id is not None:
        rows = [r for r in rows if r["interpreter_id"] == interp_id]
    if lifecycle is not None:
        rows = [r for r in rows if r["lifecycle_status"] == lifecycle]
    rows = sort_by_created(rows)
    window, limit, offset, total = paginate(rows)
    return ok_list(window, limit, offset, total)


@bp.post("/interpretation/assignments/<aid>/accept")
def accept_assignment(aid):
    uid, role = authenticate()
    require_role(role, {"Interpreter"})
    # NOTE: do not sweep-expire here — accept has its own dedicated
    # ERR_OFFER_EXPIRED check (validation priority 9) that must fire while the
    # assignment is still observed as OFFERED.
    a = db.assignments.get(aid)
    if not a:
        raise err("ERR_RESOURCE_NOT_FOUND", "Assignment not found")
    if a["lifecycle_status"] != "OFFERED":
        raise err("ERR_INVALID_STATE", "Assignment is not OFFERED")
    if uid != a["interpreter_id"]:
        raise err("ERR_NOT_OWNER", "Interpreter does not own this assignment")
    interp = db.interpreters.get(a["interpreter_id"])
    # offer expiry
    deadline = parse_iso(a["offered_at"]) + timedelta(seconds=C.OFFER_TTL_SECONDS)
    if db.clock.now() >= deadline:
        raise err("ERR_OFFER_EXPIRED", "Offer has expired")
    # capacity
    if interp["active_load"] >= interp["max_concurrent_load"]:
        raise err("ERR_INTERPRETER_AT_CAPACITY", "Interpreter at capacity")
    a["lifecycle_status"] = "ACCEPTED"
    a["_was_accepted"] = True
    a["_accepted_at"] = db.clock.now_iso()
    db.touch(a)
    engine.recompute_active_load(interp)
    if interp["active_load"] >= interp["max_concurrent_load"]:
        interp["status"] = "BUSY"
    interp["acceptance_pct"] = calc.acceptance_pct(interp["id"])
    db.touch(interp)
    return ok(a)


@bp.post("/interpretation/assignments/<aid>/decline")
def decline_assignment(aid):
    uid, role = authenticate()
    require_role(role, {"Interpreter"})
    engine.sweep_expired_offers()
    a = db.assignments.get(aid)
    if not a:
        raise err("ERR_RESOURCE_NOT_FOUND", "Assignment not found")
    if a["lifecycle_status"] != "OFFERED":
        raise err("ERR_INVALID_STATE", "Assignment is not OFFERED")
    if uid != a["interpreter_id"]:
        raise err("ERR_NOT_OWNER", "Interpreter does not own this assignment")
    a["lifecycle_status"] = "DECLINED"
    db.touch(a)
    interp = db.interpreters.get(a["interpreter_id"])
    if interp:
        engine.refresh_interpreter_computed(interp)
        db.touch(interp)
    req = db.requests.get(a["request_id"])
    if req and req["status"] == "ASSIGNED":
        req["status"] = "OPEN"
        db.touch(req)
    return ok(a)


@bp.post("/interpretation/assignments/<aid>/start-session")
def start_session(aid):
    uid, role = authenticate()
    require_role(role, {"Interpreter"})
    engine.sweep_expired_offers()
    a = db.assignments.get(aid)
    if not a:
        raise err("ERR_RESOURCE_NOT_FOUND", "Assignment not found")
    if a["lifecycle_status"] != "ACCEPTED":
        raise err("ERR_INVALID_STATE", "Assignment is not ACCEPTED")
    if uid != a["interpreter_id"]:
        raise err("ERR_NOT_OWNER", "Interpreter does not own this assignment")
    # no session already exists
    for s in db.sessions.values():
        if s["assignment_id"] == a["id"]:
            raise err("ERR_INVALID_STATE", "Session already exists for this assignment")
    req = db.requests.get(a["request_id"])
    # for SCHEDULED: clock >= window_start - EARLY_START_GRACE_SECONDS
    if a["assignment_type"] == "SCHEDULED" and req and req.get("window_start"):
        earliest = parse_iso(req["window_start"]) - timedelta(seconds=C.EARLY_START_GRACE_SECONDS)
        if db.clock.now() < earliest:
            raise err("ERR_INVALID_STATE", "Too early to start scheduled session")
    session = db.base_fields()
    session.update({
        "assignment_id": a["id"],
        "status": "CONNECTING",
        "connected_at": None,
        "ended_at": None,
        "billed_units": 0,
        "billed_amount_cents": 0,
    })
    db.sessions[session["id"]] = session
    a["lifecycle_status"] = "IN_SESSION"
    db.touch(a)
    return ok(session, 201)
