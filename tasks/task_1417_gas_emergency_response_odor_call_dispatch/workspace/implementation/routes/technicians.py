"""FieldTechnician and TechnicianShift endpoints."""
from flask import Blueprint, request

import clock
import db
import domain
import response
from auth import require_roles
from errors import ApiError
from routes.common import load_technician
from validate import (get_body, opt_bool, pagination_params, paginate, req_int,
                      req_str, sort_by_creation)

bp = Blueprint("technicians", __name__)

ALL = ("SystemAdmin", "Dispatcher", "FieldTechnician", "Supervisor", "Regulator")


@bp.route("/gas-ops/technicians", methods=["POST"])
@require_roles("SystemAdmin")
def create_technician(user_id, role):
    body = get_body()
    home_territory_id = req_str(body, "home_territory_id")
    rec = domain.new_record(common_fields=True)
    rec.update({
        "full_name": req_str(body, "full_name"),
        "badge_number": req_str(body, "badge_number"),
        "home_territory_id": home_territory_id,
        "hourly_rate_cents": req_int(body, "hourly_rate_cents"),
        "is_active": opt_bool(body, "is_active", True),
    })
    # Body-referenced FK existence
    if home_territory_id not in db.territories:
        raise ApiError("ERR_TERRITORY_NOT_FOUND", "Territory not found", 404)
    db.technicians[rec["id"]] = rec
    return response.success(domain.ser_technician(rec), 201)


@bp.route("/gas-ops/technicians", methods=["GET"])
@require_roles(*ALL)
def list_technicians(user_id, role):
    limit, offset = pagination_params()
    items = sort_by_creation(db.technicians.values())
    home = request.args.get("home_territory_id")
    if home is not None:
        items = [t for t in items if t["home_territory_id"] == home]
    page, total = paginate([domain.ser_technician(t) for t in items], limit, offset)
    return response.success_list(page, limit, offset, total)


@bp.route("/gas-ops/technicians/<technicianId>", methods=["GET"])
@require_roles(*ALL)
def get_technician(technicianId, user_id, role):
    return response.success(domain.ser_technician(load_technician(technicianId)), 200)


@bp.route("/gas-ops/technicians/<tid>/shifts", methods=["POST"])
@require_roles("SystemAdmin", "Supervisor")
def create_shift(tid, user_id, role):
    load_technician(tid)
    body = get_body()
    start = clock.parse_dt(body.get("shift_start"))
    end = clock.parse_dt(body.get("shift_end"))
    if end <= start:
        raise ApiError("ERR_INVALID_TIME_RANGE", "shift_end must be strictly after shift_start", 400)
    for s in db.shifts.values():
        if s["technician_id"] != tid:
            continue
        # Half-open intervals; adjacency (end == start) is allowed.
        if start < s["shift_end"] and s["shift_start"] < end:
            raise ApiError("ERR_SHIFT_OVERLAP",
                           "Shift overlaps an existing shift of this technician", 409)
    rec = domain.new_record(common_fields=False)
    rec.update({"technician_id": tid, "shift_start": start, "shift_end": end})
    db.shifts[rec["id"]] = rec
    return response.success(domain.ser_shift(rec), 201)


@bp.route("/gas-ops/technicians/<tid>/shifts", methods=["GET"])
@require_roles(*ALL)
def list_shifts(tid, user_id, role):
    load_technician(tid)
    limit, offset = pagination_params()
    items = sort_by_creation([s for s in db.shifts.values() if s["technician_id"] == tid])
    page, total = paginate([domain.ser_shift(s) for s in items], limit, offset)
    return response.success_list(page, limit, offset, total)


@bp.route("/gas-ops/technicians/<tid>/dispatches", methods=["GET"])
@require_roles(*ALL)
def list_technician_dispatches(tid, user_id, role):
    load_technician(tid)
    limit, offset = pagination_params()
    items = sort_by_creation(domain.assignments_of_technician(tid))
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, total = paginate([domain.ser_assignment(a) for a in items], limit, offset)
    return response.success_list(page, limit, offset, total)


@bp.route("/gas-ops/technicians/<tid>/atmospheric-readings", methods=["GET"])
@require_roles(*ALL)
def list_technician_readings(tid, user_id, role):
    load_technician(tid)
    limit, offset = pagination_params()
    items = sort_by_creation([r for r in db.readings.values() if r["technician_id"] == tid])
    page, total = paginate([domain.ser_reading(r) for r in items], limit, offset)
    return response.success_list(page, limit, offset, total)


@bp.route("/gas-ops/technicians/<tid>/make-safe-actions", methods=["GET"])
@require_roles(*ALL)
def list_technician_actions(tid, user_id, role):
    load_technician(tid)
    limit, offset = pagination_params()
    items = sort_by_creation([a for a in db.actions.values() if a["technician_id"] == tid])
    page, total = paginate([domain.ser_action(a) for a in items], limit, offset)
    return response.success_list(page, limit, offset, total)
