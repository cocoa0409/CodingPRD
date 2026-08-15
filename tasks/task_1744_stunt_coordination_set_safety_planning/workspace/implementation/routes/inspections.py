"""Inspection: record (PASSED/CONDITIONAL/FAILED outcomes), list, get."""

from flask import Blueprint, request

from db import store
from domain import (
    get_production,
    get_equipment,
    get_inspection,
    gate_posture_active,
    cascade_equipment_unavailable,
    serialize_inspection,
    stamp_new,
    touch,
    INSPECTION_OUTCOMES,
    default_sort_key,
)
from errors import err, ERR_SEGREGATION_OF_DUTIES_VIOLATION
from middleware import (
    auth,
    require_role,
    get_body,
    validate_payload,
    pagination_params,
    v_string,
    v_enum,
)
from response import ok, ok_list
from util import new_id

bp = Blueprint("inspections", __name__)

READ_ROLES = ["ProductionExecutive", "StuntCoordinator", "SafetyOfficer",
              "DepartmentHead", "Performer", "EquipmentInspector"]


@bp.post("/api/inspections")
def create_inspection():
    body = get_body()
    data = validate_payload(
        body,
        {
            "equipment_id": (v_string, True, None),
            "outcome": (v_enum(INSPECTION_OUTCOMES), True, None),
            "notes": (v_string, False, ""),
        },
    )
    user_id, role = auth()
    require_role(role, ["EquipmentInspector"])
    item = get_equipment(data["equipment_id"])
    prod = get_production(item["production_id"])
    gate_posture_active(prod)
    if user_id == item["registered_by_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES_VIOLATION,
                  "The equipment's registrar may not inspect it", 403)

    inspection = stamp_new(
        {
            "id": new_id(),
            "equipment_id": item["id"],
            "inspector_user_id": user_id,
            "outcome": data["outcome"],
            "notes": data["notes"],
            "inspected_at": store.now(),
        }
    )
    store.inspections[inspection["id"]] = inspection

    outcome = data["outcome"]
    if outcome == "PASSED":
        item["last_passed_inspection_at"] = store.now()
        if item["status"] == "QUARANTINED":
            item["status"] = "IN_SERVICE"
        touch(item)
    elif outcome == "CONDITIONAL":
        item["last_passed_inspection_at"] = store.now()
        touch(item)
    elif outcome == "FAILED":
        # FAILED never updates last_passed_inspection_at; it quarantines
        if item["status"] == "IN_SERVICE":
            item["status"] = "QUARANTINED"
            touch(item)
            cascade_equipment_unavailable(item)
    return ok(serialize_inspection(inspection), 201)


@bp.get("/api/inspections")
def list_inspections():
    _, role = auth()
    require_role(role, READ_ROLES)
    limit, offset = pagination_params()
    equipment_id = request.args.get("equipment_id")
    outcome = request.args.get("outcome")
    items = []
    for i in store.inspections.values():
        if equipment_id is not None and i["equipment_id"] != equipment_id:
            continue
        if outcome is not None and i["outcome"] != outcome:
            continue
        items.append(i)
    items.sort(key=default_sort_key)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize_inspection(i) for i in page], total, limit, offset)


@bp.get("/api/inspections/<iid>")
def get_one_inspection(iid):
    _, role = auth()
    require_role(role, READ_ROLES)
    inspection = get_inspection(iid)
    return ok(serialize_inspection(inspection), 200)
