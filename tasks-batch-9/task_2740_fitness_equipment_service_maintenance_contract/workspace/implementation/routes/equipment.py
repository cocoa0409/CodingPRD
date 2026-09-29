"""Fleet units: registration, meter readings and inspector tag-out."""
from flask import Blueprint

import db
import middleware
import response
from errors import ApiError
from services import calc, domain, validate

bp = Blueprint("equipment", __name__)


@bp.post("/fleetcare/equipment")
def create_equipment():
    middleware.auth(middleware.CONTRACT_ADMIN, middleware.SERVICE_COORDINATOR)
    body = middleware.body()
    club_id = validate.identifier(body, "club_id")
    model_id = validate.identifier(body, "model_id")
    serial_number = validate.string(body, "serial_number", min_len=1, max_len=40)
    install_date = validate.day(body, "install_date")
    initial_hours = validate.number(body, "initial_usage_hours", minimum=0,
                                    required=False, default=calc.dec(0))

    club = domain.need_club(club_id)
    domain.need_model(model_id)
    for existing in db.equipment.values():
        if existing["serial_number"] == serial_number:
            raise ApiError("ERR_SERIAL_DUPLICATE")

    hours = calc.rhu(initial_hours, 2)
    row = db.base_row()
    row.update({
        "club_id": club_id,
        "model_id": model_id,
        "serial_number": serial_number,
        "install_date": install_date,
        "usage_hours": hours,
        "usage_hours_at_last_pm": hours,
        "pm_status": "OK",
        "lifecycle_status": "IN_SERVICE",
        "support_status": "SUPPORTED",
        "downtime_minutes_ytd": 0,
        "loaner_active": False,
        "eos_notified_at": None,
        "last_safety_clearance_at": None,
        "safety_lockout_reason": None,
        "health_score": None,
        "health_score_variant": None,
        "replacement_recommended": False,
    })
    row.update(domain.condition_fields(row))
    db.equipment[row["id"]] = row
    domain.recompute_fleet_derivations(club["id"])
    return response.created_response(row)


@bp.get("/fleetcare/equipment")
def list_equipment():
    middleware.auth(*middleware.ALL_ROLES)
    return response.listing(db.equipment, {
        "club_id": response.arg("club_id"),
        "model_id": response.arg("model_id"),
        "lifecycle_status": response.arg("lifecycle_status"),
        "pm_status": response.arg("pm_status"),
        "support_status": response.arg("support_status"),
    })


@bp.get("/fleetcare/equipment/<equipment_id>")
def read_equipment(equipment_id):
    ctx = middleware.auth(*middleware.ALL_ROLES)
    row = domain.need_equipment(equipment_id)
    middleware.require_club_scope(ctx, row["club_id"])
    return response.object_response(row)


@bp.post("/fleetcare/equipment/<equipment_id>/usage-readings")
def record_usage(equipment_id):
    middleware.auth(middleware.CONTRACT_ADMIN, middleware.SERVICE_COORDINATOR,
                    middleware.FIELD_TECHNICIAN)
    row = domain.need_equipment(equipment_id)
    body = middleware.body()
    reading = validate.number(body, "usage_hours", minimum=0)
    hours = calc.rhu(reading, 2)
    if hours < calc.dec(row["usage_hours"]):
        raise ApiError("ERR_USAGE_REGRESSION")

    changes = {"usage_hours": hours}
    changes.update(domain.pm_status_fields(row, changes))
    domain.refresh_equipment_condition(row, changes)
    domain.recompute_contract_fleet(row["club_id"])
    return response.object_response(row)


@bp.post("/fleetcare/equipment/<equipment_id>/tag-out")
def tag_out(equipment_id):
    ctx = middleware.auth(middleware.SAFETY_INSPECTOR)
    middleware.require_inspector(ctx)
    row = domain.need_equipment(equipment_id)
    body = middleware.body()
    reason = validate.enum(body, "reason", calc.LOCKOUT_REASONS)

    domain.tag_out_equipment(row, reason)
    for call in db.ordered(db.calls):
        if call["equipment_id"] != row["id"]:
            continue
        if call["status"] in calc.LIVE_CALL_STATUSES:
            db.apply_changes(call, {"safety_review_required": True})
    return response.object_response(row)
