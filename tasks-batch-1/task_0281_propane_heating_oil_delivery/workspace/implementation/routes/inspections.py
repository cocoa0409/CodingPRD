"""SafetyInspection endpoints (PRD §3.8)."""
from flask import Blueprint, request

import db
from common import (parse_pagination, paginate, sort_by_created,
                    require_enum, require_iso_datetime)
from middleware import require_auth, require_role, check_owner, get_json_body
from response import object_response, array_response
from services import lookups as L

bp = Blueprint("inspections", __name__)

RESULTS = {"PASSED", "FAILED"}
READ_ROLES = {"AccountManager", "Dispatcher", "Inspector", "Customer"}


@bp.post("/tanks/<tank_id>/inspections")
def create_inspection(tank_id):
    _, role = require_auth()
    require_role(role, {"Inspector"})
    tank = L.get_tank(tank_id)
    body = get_json_body()

    result = require_enum(body, "result", RESULTS)
    inspected_at = require_iso_datetime(body, "inspected_at")
    notes = body.get("notes")
    if notes is not None and not isinstance(notes, str):
        from common import _invalid
        _invalid("notes must be a string")

    rec = {
        "tank_id": tank["id"],
        "result": result,
        "inspected_at": inspected_at,
        "notes": notes,
    }
    db.stamp_create_full(rec)
    db.safety_inspections[rec["id"]] = rec

    # Side effect on the tank's service dimension.
    if result == "FAILED" and tank["service_status"] == "IN_SERVICE":
        tank["service_status"] = "LOCKED_OUT"
        db.touch(tank)
    elif result == "PASSED" and tank["service_status"] == "LOCKED_OUT":
        tank["service_status"] = "IN_SERVICE"
        db.touch(tank)

    return object_response(L.serialize_inspection(rec), 201)


@bp.get("/safety-inspections/<inspection_id>")
def get_inspection(inspection_id):
    user_id, role = require_auth()
    require_role(role, READ_ROLES)
    rec = L.get_inspection(inspection_id)
    tank = db.tanks.get(rec["tank_id"])
    if tank is not None:
        check_owner(role, user_id, tank["account_id"])
    return object_response(L.serialize_inspection(rec), 200)


@bp.get("/safety-inspections")
def list_inspections():
    user_id, role = require_auth()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    tank_id = request.args.get("tank_id")
    result = request.args.get("result")

    items = list(db.safety_inspections.values())
    if role == "Customer":
        owned = {t["id"] for t in L.tanks_for_account(user_id)}
        items = [i for i in items if i.get("tank_id") in owned]
    if tank_id is not None:
        items = [i for i in items if i.get("tank_id") == tank_id]
    if result is not None:
        items = [i for i in items if i.get("result") == result]

    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([L.serialize_inspection(i) for i in page], limit, offset, total)
