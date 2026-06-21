"""Driver endpoints (PRD §3.1)."""
from flask import Blueprint

import db
import errors
import model
import response
import serializers as ser
import validation as val
from middleware import get_auth, require_role
from paginate import paginate

bp = Blueprint("drivers", __name__)

CYCLE_RULES = {"SEVENTY_HOUR_8_DAY", "SIXTY_HOUR_7_DAY"}
DRIVER_STATUSES = {"ACTIVE", "DEACTIVATED"}


@bp.route("/eld/drivers", methods=["POST"])
def create_driver():
    _, role = get_auth()
    require_role(role, {"CarrierAdmin"})
    body = val.get_body()

    license_number = val.require_str(body, "license_number")
    full_name = val.require_str(body, "full_name")

    tz = body.get("home_terminal_tz_offset_minutes", 0)
    if "home_terminal_tz_offset_minutes" in body and body["home_terminal_tz_offset_minutes"] is not None:
        tz = val.require_int(body, "home_terminal_tz_offset_minutes")
        if tz < -720 or tz > 840:
            raise errors.err(errors.ERR_INVALID_REQUEST, "tz offset out of bounds.")
    else:
        tz = 0

    cycle_rule = body.get("cycle_rule", "SEVENTY_HOUR_8_DAY")
    if cycle_rule is None:
        cycle_rule = "SEVENTY_HOUR_8_DAY"
    val.enum_in(cycle_rule, CYCLE_RULES, "cycle_rule")

    pc_authorized = body.get("pc_authorized", False)
    if pc_authorized is None:
        pc_authorized = False
    if not isinstance(pc_authorized, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "pc_authorized must be boolean.")

    for r in db.drivers.values():
        if r["license_number"] == license_number:
            raise errors.err(errors.ERR_DUPLICATE_LICENSE, "license_number already exists.")

    rec = {
        "license_number": license_number,
        "full_name": full_name,
        "home_terminal_tz_offset_minutes": tz,
        "cycle_rule": cycle_rule,
        "status": "ACTIVE",
        "pc_authorized": pc_authorized,
        "current_duty_status": "OFF_DUTY",
        "cycle_on_duty_minutes": 0,
    }
    model.stamp_new(rec)
    db.drivers[rec["id"]] = rec
    return response.object_response(ser.driver_view(rec), 201)


@bp.route("/eld/drivers/<id>", methods=["GET"])
def get_driver(id):
    _, role = get_auth()
    require_role(role, {"Driver", "CarrierAdmin", "SafetyOfficer"})
    rec = db.drivers.get(id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Driver not found.")
    return response.object_response(ser.driver_view(rec), 200)


@bp.route("/eld/drivers", methods=["GET"])
def list_drivers():
    _, role = get_auth()
    require_role(role, {"CarrierAdmin", "SafetyOfficer"})
    limit, offset = val.get_pagination()
    from flask import request
    status = request.args.get("status")
    items = [r for r in db.drivers.values()]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total = paginate(items, limit, offset)
    return response.array_response([ser.driver_view(r) for r in page], limit, offset, total)


@bp.route("/eld/drivers/<id>", methods=["PATCH"])
def update_driver(id):
    _, role = get_auth()
    require_role(role, {"CarrierAdmin"})
    rec = db.drivers.get(id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Driver not found.")
    body = val.get_body()

    # OCC check
    if "expected_driver_version" in body and body["expected_driver_version"] is not None:
        if body["expected_driver_version"] != rec["version"]:
            raise errors.err(errors.ERR_STALE_VERSION, "Driver version mismatch.")

    if "pc_authorized" in body and body["pc_authorized"] is not None:
        if not isinstance(body["pc_authorized"], bool):
            raise errors.err(errors.ERR_INVALID_REQUEST, "pc_authorized must be boolean.")
        rec["pc_authorized"] = body["pc_authorized"]
    if "cycle_rule" in body and body["cycle_rule"] is not None:
        val.enum_in(body["cycle_rule"], CYCLE_RULES, "cycle_rule")
        rec["cycle_rule"] = body["cycle_rule"]
    if "status" in body and body["status"] is not None:
        val.enum_in(body["status"], DRIVER_STATUSES, "status")
        rec["status"] = body["status"]

    model.touch(rec)
    return response.object_response(ser.driver_view(rec), 200)
