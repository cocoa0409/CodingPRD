"""EquipmentItem: register, retire (with cascade)."""

from flask import Blueprint, request

from db import store
from domain import (
    get_production,
    get_equipment,
    gate_posture_setup_or_active,
    cascade_equipment_unavailable,
    serialize_equipment,
    stamp_new,
    stamp_mutable,
    touch,
    EQUIPMENT_TYPES,
    default_sort_key,
)
from errors import err, ERR_EQUIPMENT_INVALID_STATE
from middleware import (
    auth,
    require_role,
    get_body,
    validate_payload,
    pagination_params,
    v_string,
    v_pos_int,
    v_enum,
)
from response import ok, ok_list
from util import new_id

bp = Blueprint("equipment", __name__)

READ_ROLES = ["ProductionExecutive", "StuntCoordinator", "SafetyOfficer",
              "DepartmentHead", "Performer", "EquipmentInspector"]
COORD = ["StuntCoordinator"]


@bp.post("/api/equipment")
def create_equipment():
    body = get_body()
    data = validate_payload(
        body,
        {
            "production_id": (v_string, True, None),
            "name": (v_string, True, None),
            "equipment_type": (v_enum(EQUIPMENT_TYPES), True, None),
            "serial_number": (v_string, True, None),
            "inspection_interval_hours": (v_pos_int, True, None),
        },
    )
    user_id, role = auth()
    require_role(role, COORD)
    prod = get_production(data["production_id"])
    gate_posture_setup_or_active(prod)

    item = stamp_mutable(
        stamp_new(
            {
                "id": new_id(),
                "production_id": prod["id"],
                "name": data["name"],
                "equipment_type": data["equipment_type"],
                "serial_number": data["serial_number"],
                "inspection_interval_hours": data["inspection_interval_hours"],
                "status": "IN_SERVICE",
                "registered_by_user_id": user_id,
                "last_passed_inspection_at": None,
            }
        )
    )
    store.equipment[item["id"]] = item
    return ok(serialize_equipment(item), 201)


@bp.get("/api/equipment")
def list_equipment():
    _, role = auth()
    require_role(role, READ_ROLES)
    limit, offset = pagination_params()
    production_id = request.args.get("production_id")
    status = request.args.get("status")
    equipment_type = request.args.get("equipment_type")
    items = []
    for e in store.equipment.values():
        if production_id is not None and e["production_id"] != production_id:
            continue
        if status is not None and e["status"] != status:
            continue
        if equipment_type is not None and e["equipment_type"] != equipment_type:
            continue
        items.append(e)
    items.sort(key=default_sort_key)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize_equipment(e) for e in page], total, limit, offset)


@bp.get("/api/equipment/<eid>")
def get_one_equipment(eid):
    _, role = auth()
    require_role(role, READ_ROLES)
    item = get_equipment(eid)
    return ok(serialize_equipment(item), 200)


@bp.post("/api/equipment/<eid>/retire")
def retire_equipment(eid):
    body = get_body()
    validate_payload(body, {})
    _, role = auth()
    require_role(role, COORD)
    item = get_equipment(eid)
    prod = get_production(item["production_id"])
    gate_posture_setup_or_active(prod)
    if item["status"] == "RETIRED":
        raise err(ERR_EQUIPMENT_INVALID_STATE,
                  "retire requires a non-RETIRED equipment item", 409)
    item["status"] = "RETIRED"
    touch(item)
    cascade_equipment_unavailable(item)
    return ok(serialize_equipment(item), 200)
