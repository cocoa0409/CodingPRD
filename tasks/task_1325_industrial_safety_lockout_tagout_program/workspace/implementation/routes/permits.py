"""Contractor permits: request, approval, activation, auto-close (PRD 3.9)."""

from flask import Blueprint, request

import db
from clock import CLOCK, parse_iso, fmt
from errors import ApiError
from middleware import auth, paginate, ALL_ROLES
from response import ok, ok_list
from services import core

bp = Blueprint("contractor_permits", __name__)


@bp.route("/contractor-permits", methods=["POST"])
def create_permit():
    user_id, _ = auth(["AuthorizedEmployee"])
    body = core.body_json()
    machine_id = core.req_str(body, "machine_id")
    company_name = core.req_str(body, "company_name")
    insurance = core.req_dt(body, "insurance_valid_until")
    m = core.get_or_404("machines", machine_id, "Machine")
    p = core.stamp_new({
        "id": core.new_id(),
        "machine_id": m["id"],
        "company_name": company_name,
        "coordinator_employee_id": user_id,
        "insurance_valid_until": fmt(insurance),
        "coordination_meeting_at": None,
        "session_id": None,
        "status": "REQUESTED",
    })
    db.DB["contractor_permits"][p["id"]] = p
    return ok(core.permit_view(p), 201)


@bp.route("/contractor-permits", methods=["GET"])
def list_permits():
    auth(ALL_ROLES)
    machine_id = request.args.get("machine_id")
    coordinator = request.args.get("coordinator_employee_id")
    session_id = request.args.get("session_id")
    status = request.args.get("status")
    items = list(db.DB["contractor_permits"].values())
    if machine_id is not None:
        items = [p for p in items if p["machine_id"] == machine_id]
    if coordinator is not None:
        items = [p for p in items if p["coordinator_employee_id"] == coordinator]
    if session_id is not None:
        items = [p for p in items if p["session_id"] == session_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.permit_view(p) for p in page], total, limit, offset)


@bp.route("/contractor-permits/<pid>", methods=["GET"])
def get_permit(pid):
    auth(ALL_ROLES)
    p = core.get_or_404("contractor_permits", pid, "ContractorPermit")
    return ok(core.permit_view(p))


@bp.route("/contractor-permits/<pid>/approve", methods=["POST"])
def approve_permit(pid):
    auth(["EHSManager"])
    body = core.body_json()
    meeting = core.req_dt(body, "coordination_meeting_at")
    p = core.get_or_404("contractor_permits", pid, "ContractorPermit")
    if p["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a REQUESTED permit can be approved")
    # PRD 3.9 guard order: coordination meeting recency, machine posture,
    # contractor insurance validity (strictly later than the clock).
    now = CLOCK.now()
    if meeting > now:
        raise ApiError("ERR_VALIDATION", 400,
                       "coordination_meeting_at must not be later than the clock")
    m = db.DB["machines"][p["machine_id"]]
    if m["status"] != "IN_SERVICE":
        raise ApiError("ERR_MACHINE_NOT_IN_SERVICE", 409, "Machine is not IN_SERVICE")
    if not parse_iso(p["insurance_valid_until"]) > now:
        raise ApiError("ERR_INSURANCE_EXPIRED", 409, "Contractor insurance has expired")
    p["coordination_meeting_at"] = fmt(meeting)
    p["status"] = "APPROVED"
    core.touch(p)
    return ok(core.permit_view(p))


@bp.route("/contractor-permits/<pid>/reject", methods=["POST"])
def reject_permit(pid):
    auth(["EHSManager"])
    p = core.get_or_404("contractor_permits", pid, "ContractorPermit")
    if p["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a REQUESTED permit can be rejected")
    p["status"] = "REJECTED"
    core.touch(p)
    return ok(core.permit_view(p))


@bp.route("/contractor-permits/<pid>/activate", methods=["POST"])
def activate_permit(pid):
    user_id, _ = auth(["AuthorizedEmployee"])
    body = core.body_json()
    session_id = core.req_str(body, "session_id")
    p = core.get_or_404("contractor_permits", pid, "ContractorPermit")
    s = core.get_or_404("lockout_sessions", session_id, "LockoutSession")
    # Ownership (stage 5): only the coordinator activates the permit.
    if p["coordinator_employee_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN", 403, "Only the coordinator may activate the permit")
    if p["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an APPROVED permit can be activated")
    if not (s["status"] == "LOCKED"
            and s["session_type"] == "CONTRACTOR"
            and s["machine_id"] == p["machine_id"]
            and s["primary_employee_id"] == p["coordinator_employee_id"]):
        raise ApiError("ERR_PERMIT_SESSION_MISMATCH", 409,
                       "Session must be a LOCKED CONTRACTOR session on the permit's "
                       "machine led by the coordinator")
    p["session_id"] = s["id"]
    p["status"] = "ACTIVE"
    core.touch(p)
    return ok(core.permit_view(p))
