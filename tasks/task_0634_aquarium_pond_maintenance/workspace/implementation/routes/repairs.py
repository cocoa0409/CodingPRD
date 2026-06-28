"""RepairOrder endpoints (PRD §3.7)."""

from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import get_auth, require_roles
from response import object_response, array_response
from serializers import repair_view
import common as C

bp = Blueprint("repairs", __name__)


@bp.post("/aquatics/repairs")
def create_repair():
    _, role = get_auth()
    require_roles(role, {"FieldTech", "AccountManager"})
    data = C.require_body(request.get_json(silent=True))
    equipment_id = C.req_str(data, "equipment_id")
    reported_symptom = C.req_str(data, "reported_symptom")
    parts_needed = C.req_bool(data, "parts_needed", allow_missing=True, default=False)

    if equipment_id not in store.equipment:
        raise ApiError("ERR_NOT_FOUND", "Equipment not found.")

    rec = C.make_record({
        "equipment_id": equipment_id,
        "reported_symptom": reported_symptom,
        "parts_needed": parts_needed,
        "status": "REPORTED",
    })
    store.repairs[rec["id"]] = rec
    return object_response(repair_view(rec), 201)


@bp.get("/aquatics/repairs/<rid>")
def get_repair(rid):
    _, role = get_auth()
    require_roles(role, {"FieldTech", "AccountManager"})
    rec = store.repairs.get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Repair order not found.")
    return object_response(repair_view(rec))


@bp.get("/aquatics/equipment/<eid>/repairs")
def list_equipment_repairs(eid):
    _, role = get_auth()
    require_roles(role, {"FieldTech", "AccountManager"})
    if eid not in store.equipment:
        raise ApiError("ERR_NOT_FOUND", "Equipment not found.")
    limit, offset = C.parse_pagination(request.args)
    status = request.args.get("status")
    recs = [r for r in store.repairs.values() if r["equipment_id"] == eid]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, total = C.paginate(recs, limit, offset)
    return array_response([repair_view(r) for r in page], limit, offset, total)


@bp.post("/aquatics/repairs/<rid>/diagnose")
def diagnose_repair(rid):
    _, role = get_auth()
    require_roles(role, {"FieldTech"})
    rec = store.repairs.get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Repair order not found.")
    if rec["status"] != "REPORTED":
        raise ApiError("ERR_INVALID_STATE", "Only a REPORTED repair may be diagnosed.")
    rec["status"] = "DIAGNOSED"
    C.touch(rec)
    eq = store.equipment.get(rec["equipment_id"])
    if eq is not None:
        eq["status"] = "DEGRADED"
        C.touch(eq)
    return object_response(repair_view(rec))


@bp.post("/aquatics/repairs/<rid>/order-parts")
def order_parts(rid):
    _, role = get_auth()
    require_roles(role, {"FieldTech"})
    rec = store.repairs.get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Repair order not found.")
    if rec["status"] != "DIAGNOSED":
        raise ApiError("ERR_INVALID_STATE", "Only a DIAGNOSED repair may order parts.")
    if not rec["parts_needed"]:
        # ordering parts when parts_needed is false is not a defined transition
        raise ApiError("ERR_INVALID_STATE", "parts_needed must be true to order parts.")
    rec["status"] = "AWAITING_PARTS"
    C.touch(rec)
    return object_response(repair_view(rec))


@bp.post("/aquatics/repairs/<rid>/parts-arrived")
def parts_arrived(rid):
    _, role = get_auth()
    require_roles(role, {"FieldTech"})
    rec = store.repairs.get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Repair order not found.")
    if rec["status"] != "AWAITING_PARTS":
        raise ApiError("ERR_INVALID_STATE", "Only an AWAITING_PARTS repair may receive parts.")
    rec["status"] = "DIAGNOSED"
    C.touch(rec)
    return object_response(repair_view(rec))


@bp.post("/aquatics/repairs/<rid>/close")
def close_repair(rid):
    _, role = get_auth()
    require_roles(role, {"FieldTech"})
    rec = store.repairs.get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Repair order not found.")
    if rec["status"] != "DIAGNOSED":
        raise ApiError("ERR_INVALID_STATE", "Only a DIAGNOSED repair may be closed.")
    eq = store.equipment.get(rec["equipment_id"])
    if eq is not None and eq["status"] == "OUT_OF_SERVICE":
        raise ApiError("ERR_INVALID_STATE", "Cannot close: equipment is OUT_OF_SERVICE.")
    rec["status"] = "CLOSED"
    C.touch(rec)
    if eq is not None:
        eq["status"] = "OPERATIONAL"
        C.touch(eq)
    return object_response(repair_view(rec))


@bp.post("/aquatics/repairs/<rid>/scrap")
def scrap_repair(rid):
    _, role = get_auth()
    require_roles(role, {"FieldTech"})
    rec = store.repairs.get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Repair order not found.")
    if rec["status"] != "DIAGNOSED":
        raise ApiError("ERR_INVALID_STATE", "Only a DIAGNOSED repair may be scrapped.")
    rec["status"] = "SCRAPPED"
    C.touch(rec)
    eq = store.equipment.get(rec["equipment_id"])
    if eq is not None:
        eq["status"] = "OUT_OF_SERVICE"
        C.touch(eq)
    return object_response(repair_view(rec))
