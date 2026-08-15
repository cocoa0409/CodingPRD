"""Employee locks and group lockout (PRD 3.6)."""

from flask import Blueprint, request

import db
from clock import CLOCK, fmt
from errors import ApiError
from middleware import auth, paginate, ALL_ROLES
from response import ok, ok_list
from services import core

bp = Blueprint("employee_locks", __name__)


@bp.route("/employee-locks", methods=["POST"])
def create_lock():
    user_id, _ = auth(["AuthorizedEmployee"])
    body = core.body_json()
    session_id = core.req_str(body, "session_id")
    lock_no = core.req_str(body, "lock_no")
    tag_no = core.req_str(body, "tag_no")
    s = core.get_or_404("lockout_sessions", session_id, "LockoutSession")
    # Issuance guards, in the PRD 3.6 order: competency, lock_no uniqueness,
    # already-on-session, then the pinned lock-point capacity.
    if not core.actor_qualified(user_id):
        raise ApiError("ERR_TRAINING_NOT_CURRENT", 409,
                       "Issuer is not a currently qualified authorized employee")
    for l in db.DB["employee_locks"].values():
        if l["lock_no"] == lock_no and l["status"] in core.NONTERMINAL_LOCK_STATUSES:
            raise ApiError("ERR_DUPLICATE_LOCK_NO", 409,
                           "lock_no is already in use by a non-terminal lock")
    for l in db.DB["employee_locks"].values():
        if (l["session_id"] == session_id and l["employee_id"] == user_id
                and l["status"] in core.NONTERMINAL_LOCK_STATUSES):
            raise ApiError("ERR_ALREADY_ON_SESSION", 409,
                           "Employee already holds a non-terminal lock on this session")
    # calculations.session_lock_capacity: read the PINNED max_locks, count
    # non-terminal locks, reject when the count already equals the pin.
    non_terminal = sum(1 for l in db.DB["employee_locks"].values()
                       if l["session_id"] == session_id
                       and l["status"] in core.NONTERMINAL_LOCK_STATUSES)
    if non_terminal >= s["max_locks"]:
        raise ApiError("ERR_LOCK_POINT_CAPACITY", 409,
                       "Session lock-point capacity reached")
    l = core.stamp_new({
        "id": core.new_id(),
        "session_id": s["id"],
        "employee_id": user_id,
        "lock_no": lock_no,
        "tag_no": tag_no,
        "applied_at": None,
        "removed_at": None,
        "removal_reason": None,
        "status": "ISSUED",
    })
    db.DB["employee_locks"][l["id"]] = l
    return ok(core.lock_view(l), 201)


@bp.route("/employee-locks", methods=["GET"])
def list_locks():
    auth(ALL_ROLES)
    session_id = request.args.get("session_id")
    employee_id = request.args.get("employee_id")
    status = request.args.get("status")
    items = list(db.DB["employee_locks"].values())
    if session_id is not None:
        items = [l for l in items if l["session_id"] == session_id]
    if employee_id is not None:
        items = [l for l in items if l["employee_id"] == employee_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.lock_view(l) for l in page], total, limit, offset)


@bp.route("/employee-locks/<lid>", methods=["GET"])
def get_lock(lid):
    auth(ALL_ROLES)
    l = core.get_or_404("employee_locks", lid, "EmployeeLock")
    return ok(core.lock_view(l))


@bp.route("/employee-locks/<lid>/apply", methods=["POST"])
def apply_lock(lid):
    user_id, _ = auth(["AuthorizedEmployee"])
    l = core.get_or_404("employee_locks", lid, "EmployeeLock")
    # Ownership (stage 5): only the lock's owner may apply it.
    if l["employee_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN", 403, "Only the lock owner may apply the lock")
    if l["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an ISSUED lock can be applied")
    s = db.DB["lockout_sessions"][l["session_id"]]
    if s["status"] not in ("SETUP", "LOCKED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "The owning session must be in SETUP or LOCKED")
    l["status"] = "APPLIED"
    l["applied_at"] = fmt(CLOCK.now())
    core.touch(l)
    return ok(core.lock_view(l))


@bp.route("/employee-locks/<lid>/remove", methods=["POST"])
def remove_lock(lid):
    user_id, _ = auth(["AuthorizedEmployee"])
    l = core.get_or_404("employee_locks", lid, "EmployeeLock")
    if l["employee_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN", 403, "Only the lock owner may remove the lock")
    if l["status"] != "APPLIED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an APPLIED lock can be removed")
    s = db.DB["lockout_sessions"][l["session_id"]]
    if s["status"] != "LOCKED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "The owning session must be LOCKED")
    l["status"] = "REMOVED"
    l["removed_at"] = fmt(CLOCK.now())
    core.touch(l)
    return ok(core.lock_view(l))


@bp.route("/employee-locks/<lid>/force-remove", methods=["POST"])
def force_remove_lock(lid):
    user_id, _ = auth(["EHSManager"])
    body = core.body_json()
    reason = core.req_str(body, "reason")
    l = core.get_or_404("employee_locks", lid, "EmployeeLock")
    if l["status"] != "APPLIED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an APPLIED lock can be force-removed")
    s = db.DB["lockout_sessions"][l["session_id"]]
    if s["status"] != "LOCKED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "The owning session must be LOCKED")
    # Segregation of duties (stage 8): a manager never force-removes their own lock.
    if l["employee_id"] == user_id:
        raise ApiError("ERR_SELF_APPROVAL_FORBIDDEN", 409,
                       "The lock owner may not force-remove their own lock")
    l["status"] = "FORCE_REMOVED"
    l["removed_at"] = fmt(CLOCK.now())
    l["removal_reason"] = reason
    core.touch(l)
    return ok(core.lock_view(l))
