"""Lockout sessions: planning, isolation, clearing, release, cancel (PRD 3.5)."""

from flask import Blueprint, request

import db
from clock import CLOCK, parse_iso, fmt
from errors import ApiError
from middleware import auth, paginate, ALL_ROLES
from response import ok, ok_list
from services import core

bp = Blueprint("lockout_sessions", __name__)

_SESSION_TYPES = ("INDIVIDUAL", "GROUP", "CONTRACTOR")


@bp.route("/lockout-sessions", methods=["POST"])
def create_session():
    user_id, _ = auth(["AuthorizedEmployee"])
    body = core.body_json()
    machine_id = core.req_str(body, "machine_id")
    procedure_id = core.req_str(body, "procedure_id")
    session_type = core.req_enum(body, "session_type", _SESSION_TYPES)
    m = core.get_or_404("machines", machine_id, "Machine")
    proc = core.get_or_404("lockout_procedures", procedure_id, "LockoutProcedure")
    if proc["machine_id"] != m["id"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Procedure belongs to a different machine")
    # Creation guards run in the PRD 3.5 order (which matches the pipeline of
    # section 2.8): posture, procedure currency, audit currency, competency,
    # machine occupation, then the contractor-permit guard.
    if m["status"] != "IN_SERVICE":
        raise ApiError("ERR_MACHINE_NOT_IN_SERVICE", 409, "Machine is not IN_SERVICE")
    if proc["status"] != "ACTIVE":
        raise ApiError("ERR_PROCEDURE_NOT_ACTIVE", 409, "Procedure is not ACTIVE")
    # Overdue predicate is strict >: the exact audit_due_at instant still passes.
    if CLOCK.now() > parse_iso(proc["audit_due_at"]):
        raise ApiError("ERR_AUDIT_OVERDUE", 409, "The procedure's audit is overdue")
    if not core.actor_qualified(user_id):
        raise ApiError("ERR_TRAINING_NOT_CURRENT", 409,
                       "Creator is not a currently qualified authorized employee")
    # Occupation is the half-open interval [created_at, ended_at): any session
    # in SETUP / LOCKED / CLEARED still occupies the machine.
    for s in db.DB["lockout_sessions"].values():
        if s["machine_id"] == m["id"] and s["status"] in core.OPEN_SESSION_STATUSES:
            raise ApiError("ERR_MACHINE_SESSION_CONFLICT", 409,
                           "Machine already has an open lockout session")
    if session_type == "CONTRACTOR":
        has_permit = any(p for p in db.DB["contractor_permits"].values()
                         if p["machine_id"] == m["id"] and p["status"] == "APPROVED")
        if not has_permit:
            raise ApiError("ERR_PERMIT_REQUIRED", 409,
                           "A CONTRACTOR session requires an APPROVED permit for the machine")
    s = core.stamp_new({
        "id": core.new_id(),
        "machine_id": m["id"],
        "procedure_id": proc["id"],
        # Version pinning: both pins are copies taken at creation and are never
        # refreshed, however the procedure evolves afterwards (PRD 3.5).
        "procedure_revision_no": proc["revision_no"],
        "max_locks": proc["isolation_point_count"],
        "session_type": session_type,
        "primary_employee_id": user_id,
        "zero_energy_verified": False,
        "started_at": None,
        "ended_at": None,
        "status": "SETUP",
    })
    db.DB["lockout_sessions"][s["id"]] = s
    return ok(core.session_view(s), 201)


@bp.route("/lockout-sessions", methods=["GET"])
def list_sessions():
    auth(ALL_ROLES)
    machine_id = request.args.get("machine_id")
    procedure_id = request.args.get("procedure_id")
    primary = request.args.get("primary_employee_id")
    status = request.args.get("status")
    items = list(db.DB["lockout_sessions"].values())
    if machine_id is not None:
        items = [s for s in items if s["machine_id"] == machine_id]
    if procedure_id is not None:
        items = [s for s in items if s["procedure_id"] == procedure_id]
    if primary is not None:
        items = [s for s in items if s["primary_employee_id"] == primary]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.session_view(s) for s in page], total, limit, offset)


@bp.route("/lockout-sessions/<sid>", methods=["GET"])
def get_session(sid):
    auth(ALL_ROLES)
    s = core.get_or_404("lockout_sessions", sid, "LockoutSession")
    return ok(core.session_view(s))


def _owned_session(sid, user_id):
    s = core.get_or_404("lockout_sessions", sid, "LockoutSession")
    # Ownership (stage 5): lock / clear / release / cancel are primary-only.
    if s["primary_employee_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Only the session's primary employee may drive this transition")
    return s


@bp.route("/lockout-sessions/<sid>/lock", methods=["POST"])
def lock_session(sid):
    user_id, _ = auth(["AuthorizedEmployee"])
    body = core.body_json()
    s = _owned_session(sid, user_id)
    if s["status"] != "SETUP":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a SETUP session can be locked")
    # PRD 3.5 order: machine posture, procedure currency, locks, zero energy.
    m = db.DB["machines"][s["machine_id"]]
    if m["status"] != "IN_SERVICE":
        raise ApiError("ERR_MACHINE_NOT_IN_SERVICE", 409, "Machine is not IN_SERVICE")
    proc = db.DB["lockout_procedures"][s["procedure_id"]]
    if proc["status"] != "ACTIVE":
        raise ApiError("ERR_PROCEDURE_NOT_ACTIVE", 409, "Procedure is not ACTIVE")
    if core.applied_lock_count(sid) < 1:
        raise ApiError("ERR_NO_LOCKS_APPLIED", 409, "At least one lock must be applied")
    if body.get("zero_energy_verified") is not True:
        raise ApiError("ERR_ZERO_ENERGY_NOT_VERIFIED", 409,
                       "zero_energy_verified must be true to complete isolation")
    s["status"] = "LOCKED"
    s["started_at"] = fmt(CLOCK.now())
    s["zero_energy_verified"] = True
    core.touch(s)
    return ok(core.session_view(s))


@bp.route("/lockout-sessions/<sid>/clear", methods=["POST"])
def clear_session(sid):
    user_id, _ = auth(["AuthorizedEmployee"])
    s = _owned_session(sid, user_id)
    if s["status"] != "LOCKED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a LOCKED session can be cleared")
    if core.applied_lock_count(sid) != 0:
        raise ApiError("ERR_LOCKS_STILL_APPLIED", 409,
                       "Every lock must be off the machine before clearing")
    s["status"] = "CLEARED"
    core.touch(s)
    return ok(core.session_view(s))


@bp.route("/lockout-sessions/<sid>/release", methods=["POST"])
def release_session(sid):
    user_id, _ = auth(["AuthorizedEmployee"])
    s = _owned_session(sid, user_id)
    if s["status"] != "CLEARED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a CLEARED session can be released")
    s["status"] = "RELEASED"
    s["ended_at"] = fmt(CLOCK.now())
    core.touch(s)
    # Cascade: any contractor permit bound to this session closes (PRD 3.9).
    for p in db.DB["contractor_permits"].values():
        if p["session_id"] == sid and p["status"] == "ACTIVE":
            p["status"] = "CLOSED"
            core.touch(p)
    return ok(core.session_view(s))


@bp.route("/lockout-sessions/<sid>/cancel", methods=["POST"])
def cancel_session(sid):
    user_id, _ = auth(["AuthorizedEmployee"])
    s = _owned_session(sid, user_id)
    if s["status"] != "SETUP":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a SETUP session can be cancelled")
    core.cancel_setup_session(s)
    return ok(core.session_view(s))
