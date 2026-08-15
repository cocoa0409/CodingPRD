"""Construction crews and permit milestones."""

from flask import Blueprint

from db import db
from errors import ApiError, not_found, invalid_state, already_terminal
from middleware import require_roles, ALL_API_ROLES
from response import ok_object
from services import (
    new_record, touch, lower_milestones_completed, ser_crew, ser_milestone,
)
from util import get_body, req_str, req_enum, req_date, fk_exists, list_response

bp = Blueprint("build", __name__)

_MILESTONE_TYPES = ("PERMIT_SUBMITTED", "PERMIT_APPROVED", "BUILD_START",
                    "BUILD_COMPLETE")


# ---------------------------------------------------------------------------
# Construction crews
# ---------------------------------------------------------------------------

@bp.post("/api/construction-crews")
def create_crew():
    require_roles("PlatformAdmin")
    body = get_body(required=True)
    code = req_str(body, "crew_code")
    for c in db.crews.values():
        if c["crew_code"] == code:
            raise ApiError(
                "ERR_CREW_CODE_TAKEN", 409,
                f"crew_code {code} is already taken")
    rec = new_record()
    rec.update({"crew_code": code, "crew_status": "ACTIVE"})
    db.crews[rec["id"]] = rec
    return ok_object(ser_crew(rec), status=201)


@bp.get("/api/construction-crews")
def list_crews():
    require_roles(*ALL_API_ROLES)
    return list_response(db.crews.values(), ser_crew)


@bp.get("/api/construction-crews/<cid>")
def get_crew(cid):
    require_roles(*ALL_API_ROLES)
    rec = db.crews.get(cid)
    if rec is None:
        raise not_found(f"ConstructionCrew not found: {cid}")
    return ok_object(ser_crew(rec))


@bp.post("/api/construction-crews/<cid>/retire")
def retire_crew(cid):
    require_roles("PlatformAdmin")
    rec = db.crews.get(cid)
    if rec is None:
        raise not_found(f"ConstructionCrew not found: {cid}")
    if rec["crew_status"] == "RETIRED":
        raise already_terminal("ConstructionCrew is RETIRED")
    rec["crew_status"] = "RETIRED"
    touch(rec)
    return ok_object(ser_crew(rec))


# ---------------------------------------------------------------------------
# Permit milestones
# ---------------------------------------------------------------------------

@bp.post("/api/permit-milestones")
def create_milestone():
    require_roles("ConstructionManager")
    body = get_body(required=True)
    site = fk_exists(body, "site_id", db.sites)
    mtype = req_enum(body, "milestone_type", _MILESTONE_TYPES)
    planned_raw, _ = req_date(body, "planned_date")
    if site["site_status"] not in ("LEASE_EXECUTED", "BUILD_OUT"):
        raise invalid_state(
            f"Site in {site['site_status']} does not accept milestones")
    for m in db.milestones.values():
        if m["site_id"] == site["id"] and m["milestone_type"] == mtype:
            raise ApiError(
                "ERR_DUPLICATE_MILESTONE", 409,
                f"A {mtype} milestone already exists for this site")
    rec = new_record()
    rec.update({
        "site_id": site["id"],
        "milestone_type": mtype,
        "planned_date": planned_raw,
        "actual_date": None,
        "milestone_status": "PENDING",
    })
    db.milestones[rec["id"]] = rec
    return ok_object(ser_milestone(rec), status=201)


@bp.get("/api/permit-milestones")
def list_milestones():
    require_roles(*ALL_API_ROLES)
    return list_response(db.milestones.values(), ser_milestone,
                         filters=["site_id", "milestone_status"])


@bp.get("/api/permit-milestones/<mid>")
def get_milestone(mid):
    require_roles(*ALL_API_ROLES)
    rec = db.milestones.get(mid)
    if rec is None:
        raise not_found(f"PermitMilestone not found: {mid}")
    return ok_object(ser_milestone(rec))


@bp.post("/api/permit-milestones/<mid>/complete")
def complete_milestone(mid):
    require_roles("ConstructionManager")
    rec = db.milestones.get(mid)
    if rec is None:
        raise not_found(f"PermitMilestone not found: {mid}")
    body = get_body(required=True)
    actual_raw, _ = req_date(body, "actual_date")
    if rec["milestone_status"] == "COMPLETED":
        raise already_terminal("PermitMilestone is COMPLETED")
    if not lower_milestones_completed(rec["site_id"], rec["milestone_type"]):
        raise ApiError(
            "ERR_MILESTONE_OUT_OF_ORDER", 409,
            "A lower-order milestone for this site is not COMPLETED")
    rec["milestone_status"] = "COMPLETED"
    rec["actual_date"] = actual_raw
    touch(rec)
    if rec["milestone_type"] == "BUILD_START":
        site = db.sites[rec["site_id"]]
        if site["site_status"] == "LEASE_EXECUTED":
            site["site_status"] = "BUILD_OUT"
            touch(site)
    return ok_object(ser_milestone(rec))
