"""Vendor engagements: half-open access windows, scope conflicts, deliverables."""
from flask import Blueprint, g, request

from db import db, parse_dt, new_entity, now_iso, now_dt
from errors import ApiError
from middleware import require_roles
from response import ok_object, ok_list
from util import (
    get_body,
    req_str,
    req_datetime,
    req_str_list,
    get_or_404,
    page_of,
    serialize,
    touch,
)

bp = Blueprint("vendors", __name__)

VENDOR_READ_ROLES = ("ProgramDirector", "EvaluationLead", "DataSteward")


@bp.post("/programs/<pid>/vendor-engagements")
@require_roles("ProgramDirector")
def create_engagement(pid):
    get_or_404(db.programs, pid)
    body = get_body()
    vendor_name = req_str(body, "vendor_name")
    scope = req_str_list(body, "scope_program_cycle_ids")
    access_start = req_datetime(body, "access_start")
    access_end = req_datetime(body, "access_end")
    deliverable_due = req_datetime(body, "deliverable_due")
    # Half-open overlap: touching windows are NOT an overlap (PRD 2.6).
    s1, e1 = parse_dt(access_start), parse_dt(access_end)
    scope_set = set(scope)
    for other in db.engagements.values():
        if other["program_id"] != pid or other["status"] not in ("PROPOSED", "ACTIVE"):
            continue
        if not scope_set.intersection(other["scope_program_cycle_ids"]):
            continue
        s2, e2 = parse_dt(other["access_start"]), parse_dt(other["access_end"])
        if s1 < e2 and s2 < e1:
            raise ApiError(
                "ERR_ENGAGEMENT_WINDOW_OVERLAP",
                409,
                "Engagement window overlaps a conflicting engagement of this program.",
            )
    ent = new_entity(
        db.engagements,
        {
            "program_id": pid,
            "vendor_name": vendor_name,
            "scope_program_cycle_ids": scope,
            "access_start": access_start,
            "access_end": access_end,
            "deliverable_due": deliverable_due,
            "deliverable_received_at": None,
            "status": "PROPOSED",
        },
    )
    return ok_object(serialize(ent), 201)


@bp.get("/programs/<pid>/vendor-engagements")
@require_roles(*VENDOR_READ_ROLES)
def list_engagements(pid):
    get_or_404(db.programs, pid)
    items = [e for e in db.engagements.values() if e["program_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    data, limit, offset, total = page_of(items)
    return ok_list(data, limit, offset, total)


@bp.get("/vendor-engagements/<eid>")
@require_roles(*VENDOR_READ_ROLES, "VendorAnalyst")
def get_engagement(eid):
    if g.role == "VendorAnalyst" and g.user_id != eid:
        raise ApiError("ERR_SCOPE_DENIED", 403, "VendorAnalyst may read only its own engagement.")
    return ok_object(serialize(get_or_404(db.engagements, eid)))


@bp.post("/vendor-engagements/<eid>/activate")
@require_roles("ProgramDirector")
def activate_engagement(eid):
    engagement = get_or_404(db.engagements, eid)
    get_body()
    if engagement["status"] != "PROPOSED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Engagement in state {engagement['status']} cannot be activated.",
        )
    program = db.programs.get(engagement["program_id"])
    if program is None or program["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Engagement activation requires the program to be ACTIVE."
        )
    engagement["status"] = "ACTIVE"
    touch(db.engagements, engagement)
    return ok_object(serialize(engagement))


@bp.post("/vendor-engagements/<eid>/complete")
@require_roles("ProgramDirector")
def complete_engagement(eid):
    engagement = get_or_404(db.engagements, eid)
    get_body()
    if engagement["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Engagement in state {engagement['status']} cannot be completed.",
        )
    if engagement["deliverable_received_at"] is None:
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Engagement cannot complete before the deliverable is received."
        )
    engagement["status"] = "COMPLETED"
    touch(db.engagements, engagement)
    return ok_object(serialize(engagement))


@bp.post("/vendor-engagements/<eid>/terminate")
@require_roles("ProgramDirector")
def terminate_engagement(eid):
    engagement = get_or_404(db.engagements, eid)
    get_body()
    if engagement["status"] not in ("PROPOSED", "ACTIVE"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Engagement in state {engagement['status']} cannot be terminated.",
        )
    engagement["status"] = "TERMINATED"
    touch(db.engagements, engagement)
    return ok_object(serialize(engagement))


@bp.post("/vendor-engagements/<eid>/submit-deliverable")
@require_roles("VendorAnalyst")
def submit_deliverable(eid):
    # Scope checks (priority 4) precede existence and body validation.
    if g.user_id != eid:
        raise ApiError("ERR_SCOPE_DENIED", 403, "VendorAnalyst may act only on its own engagement.")
    engagement = get_or_404(db.engagements, eid)
    if engagement["status"] != "ACTIVE":
        raise ApiError("ERR_SCOPE_DENIED", 403, "Vendor engagement is not ACTIVE.")
    now = now_dt()
    if not (parse_dt(engagement["access_start"]) <= now < parse_dt(engagement["access_end"])):
        raise ApiError("ERR_SCOPE_DENIED", 403, "Current time is outside the engagement window.")
    body = get_body()
    req_str(body, "note")
    engagement["deliverable_received_at"] = now_iso()
    touch(db.engagements, engagement)
    return ok_object(serialize(engagement))
