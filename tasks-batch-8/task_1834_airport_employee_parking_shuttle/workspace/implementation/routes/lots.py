"""ParkingLot endpoints."""
from flask import Blueprint, request

import db
from domain import get_or_404, serialize_lot, lot_occupied, lot_reserved, promotion_pass
from errors import raise_error
from middleware import require_roles
from response import success_object, success_list
from pagination import parse_pagination

bp = Blueprint("lots", __name__)

ALL_ROLES = ("ParkingAdmin", "Employee", "PayrollAdmin",
             "EnforcementOfficer", "AppealsOfficer", "ShuttleDispatcher")


@bp.route("/parking/lots", methods=["POST"])
def create_lot():
    require_roles("ParkingAdmin")
    body = request.get_json(silent=True)
    if body is None:
        raise_error("ERR_INVALID_REQUEST", "Malformed JSON body")
    for field in ("program_id", "code", "tier", "capacity"):
        if body.get(field) is None:
            raise_error("ERR_INVALID_REQUEST", f"{field} is required")
    program = get_or_404(db.programs, body["program_id"])
    if body["tier"] not in ("CORE", "REMOTE"):
        raise_error("ERR_INVALID_REQUEST", "invalid tier")
    capacity = body["capacity"]
    if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 0:
        raise_error("ERR_INVALID_REQUEST", "capacity must be >= 0")
    maint = body.get("monthly_maintenance_cents", 0)
    if not isinstance(maint, int) or isinstance(maint, bool) or maint < 0:
        raise_error("ERR_INVALID_REQUEST", "monthly_maintenance_cents must be >= 0")
    for l in db.lots.values():
        if l["program_id"] == program["id"] and l["code"] == body["code"]:
            raise_error("ERR_INVALID_REQUEST", "lot code already used in this program")
    rec = db.new_record({
        "program_id": program["id"],
        "code": body["code"],
        "tier": body["tier"],
        "capacity": capacity,
        "monthly_maintenance_cents": maint,
        "status": "ACTIVE" if body["tier"] == "CORE" else "STANDBY",
    })
    db.lots[rec["id"]] = rec
    return success_object(serialize_lot(rec), 201)


@bp.route("/parking/lots/<lid>", methods=["GET"])
def get_lot(lid):
    require_roles(*ALL_ROLES)
    rec = get_or_404(db.lots, lid)
    return success_object(serialize_lot(rec), 200)


@bp.route("/parking/lots", methods=["GET"])
def list_lots():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    program_id = request.args.get("program_id")
    tier = request.args.get("tier")
    status = request.args.get("status")
    items = sorted(db.lots.values(), key=lambda l: l["created_at"])
    out = []
    for l in items:
        if program_id is not None and l["program_id"] != program_id:
            continue
        if tier is not None and l["tier"] != tier:
            continue
        if status is not None and l["status"] != status:
            continue
        out.append(serialize_lot(l))
    total = len(out)
    return success_list(out[offset:offset + limit], limit, offset, total)


@bp.route("/parking/lots/<lid>", methods=["PATCH"])
def patch_lot(lid):
    require_roles("ParkingAdmin")
    lot = get_or_404(db.lots, lid)
    body = request.get_json(silent=True)
    if body is None:
        raise_error("ERR_INVALID_REQUEST", "Malformed JSON body")
    if "capacity" in body:
        capacity = body["capacity"]
        if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 0:
            raise_error("ERR_INVALID_REQUEST", "capacity must be >= 0")
        floor = lot_occupied(lid) + lot_reserved(lid)
        if capacity < floor:
            raise_error("ERR_CAPACITY_BELOW_OCCUPANCY",
                        "capacity may not be set below occupied_slots + reserved_slots")
        increased = capacity > lot["capacity"]
        lot["capacity"] = capacity
        db.touch(lot)
        if increased:
            promotion_pass(lid)
    return success_object(serialize_lot(lot), 200)
