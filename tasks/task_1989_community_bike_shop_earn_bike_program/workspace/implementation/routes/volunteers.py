"""Volunteer registry: promotion, suspension, reinstatement (PRD §3.5)."""

from flask import Blueprint, request

from db import db
from errors import ApiError
from middleware import require_roles, get_body, validate_payload
from response import success
from services.core import make_common, touch, paginate, sorted_by_created, PROMOTION

bp = Blueprint("volunteers", __name__)


def volunteer_view(v):
    return {
        "id": v["id"],
        "full_name": v["full_name"],
        "email": v["email"],
        "skill_level": v["skill_level"],
        "engagement_status": v["engagement_status"],
        "training_hours": v["training_hours"],
        "sessions_attended": v["sessions_attended"],
        "inspections_conducted": v["inspections_conducted"],
        "no_show_count": v["no_show_count"],
        "shift_minutes": v["shift_minutes"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def _get_volunteer(volunteer_id):
    vol = db.volunteers.get(volunteer_id)
    if vol is None:
        raise ApiError("ERR_NOT_FOUND", f"Volunteer {volunteer_id} does not exist")
    return vol


@bp.post("/volunteers")
def create_volunteer():
    require_roles("ShopCoordinator")
    body = get_body()
    validate_payload(body, {
        "full_name": {"type": "string", "required": True},
        "email": {"type": "string", "required": True},
    })
    vol = make_common()
    vol.update({
        "full_name": body["full_name"],
        "email": body["email"],
        "skill_level": "TRAINEE",
        "engagement_status": "ACTIVE",
        "training_hours": 0,
        "sessions_attended": 0,
        "inspections_conducted": 0,
        "no_show_count": 0,
        "shift_minutes": 0,
    })
    db.volunteers[vol["id"]] = vol
    return success(volunteer_view(vol), status=201)


@bp.get("/volunteers/<volunteer_id>")
def get_volunteer(volunteer_id):
    require_roles("ShopCoordinator", "ProgramDirector", "Volunteer")
    return success(volunteer_view(_get_volunteer(volunteer_id)))


@bp.get("/volunteers")
def list_volunteers():
    require_roles("ShopCoordinator", "ProgramDirector")
    rows = list(db.volunteers.values())
    for param in ("skill_level", "engagement_status"):
        value = request.args.get(param)
        if value is not None:
            rows = [v for v in rows if v[param] == value]
    rows = sorted_by_created(rows)
    page, pg = paginate(rows)
    return success([volunteer_view(v) for v in page], pagination=pg)


@bp.post("/volunteers/<volunteer_id>/promote")
def promote_volunteer(volunteer_id):
    require_roles("ProgramDirector")
    vol = _get_volunteer(volunteer_id)
    if vol["engagement_status"] != "ACTIVE":
        raise ApiError("ERR_VOLUNTEER_SUSPENDED", "Suspended volunteers cannot be promoted")
    step = PROMOTION.get(vol["skill_level"])
    if step is None:
        raise ApiError("ERR_INVALID_STATE", "Volunteer is already at the highest skill level")
    next_level, thresholds = step
    for field, minimum in thresholds.items():
        if vol[field] < minimum:
            raise ApiError("ERR_PROMOTION_CRITERIA_NOT_MET", "Promotion thresholds not met")
    vol["skill_level"] = next_level
    touch(vol)
    return success(volunteer_view(vol))


@bp.post("/volunteers/<volunteer_id>/suspend")
def suspend_volunteer(volunteer_id):
    require_roles("ProgramDirector")
    body = get_body()
    validate_payload(body, {"reason": {"type": "string"}})
    vol = _get_volunteer(volunteer_id)
    if vol["engagement_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE volunteer can be suspended")
    vol["engagement_status"] = "SUSPENDED"
    # Cascade: every remaining SCHEDULED shift of this volunteer -> CANCELLED.
    for shift in db.shifts.values():
        if shift["volunteer_id"] == vol["id"] and shift["status"] == "SCHEDULED":
            shift["status"] = "CANCELLED"
            touch(shift)
    touch(vol)
    return success(volunteer_view(vol))


@bp.post("/volunteers/<volunteer_id>/reinstate")
def reinstate_volunteer(volunteer_id):
    require_roles("ProgramDirector")
    vol = _get_volunteer(volunteer_id)
    if vol["engagement_status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUSPENDED volunteer can be reinstated")
    vol["engagement_status"] = "ACTIVE"
    vol["no_show_count"] = 0
    touch(vol)
    return success(volunteer_view(vol))
