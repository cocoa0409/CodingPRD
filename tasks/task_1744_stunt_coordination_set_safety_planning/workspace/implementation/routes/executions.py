"""StuntExecution: attempt (OCC), complete, abort."""

from flask import Blueprint, request

from db import store
from domain import (
    get_production,
    get_sequence,
    get_execution,
    gate_posture_active,
    inspection_current,
    required_permit_types,
    serialize_execution,
    stamp_new,
    stamp_mutable,
    touch,
    INCIDENT_SEVERITIES,
    TAKE_BONUS_CENTS,
    default_sort_key,
)
from errors import (
    err,
    ERR_VALIDATION,
    ERR_NOT_RESOURCE_OWNER,
    ERR_STALE_VERSION,
    ERR_SEQUENCE_INVALID_STATE,
    ERR_EXECUTION_INVALID_STATE,
    ERR_DUPLICATE_TAKE_NUMBER,
    ERR_CROSS_PRODUCTION_REFERENCE,
    ERR_PERMIT_MISSING_OR_WINDOW_MISMATCH,
    ERR_EQUIPMENT_NOT_READY,
)
from middleware import (
    auth,
    require_role,
    get_body,
    validate_payload,
    pagination_params,
    v_string,
    v_bool,
    v_take_number,
    v_int,
    v_enum,
)
from response import ok, ok_list
from util import new_id
from routes.incidents import create_incident_record

bp = Blueprint("executions", __name__)

READ_ROLES = ["ProductionExecutive", "StuntCoordinator", "SafetyOfficer",
              "DepartmentHead", "Performer", "EquipmentInspector"]
COORD = ["StuntCoordinator"]


def _owner_check(seq, user_id):
    if user_id != seq["coordinator_user_id"]:
        raise err(ERR_NOT_RESOURCE_OWNER,
                  "Only the coordinator who owns the sequence may perform this "
                  "action", 403)


@bp.post("/api/stunt-executions")
def create_execution():
    body = get_body()
    data = validate_payload(
        body,
        {
            "production_id": (v_string, True, None),
            "sequence_id": (v_string, True, None),
            "take_number": (v_take_number, True, None),
            "expected_sequence_version": (v_int, True, None),
        },
    )
    user_id, role = auth()
    require_role(role, COORD)

    get_production(data["production_id"])
    seq = get_sequence(data["sequence_id"])
    _owner_check(seq, user_id)

    # OCC (tier 4) precedes the posture gate (tier 5)
    if data["expected_sequence_version"] != seq["version"]:
        raise err(ERR_STALE_VERSION,
                  "expected_sequence_version does not match the sequence's current "
                  "version", 412)

    prod = get_production(seq["production_id"])
    gate_posture_active(prod)

    if seq["status"] != "READY":
        raise err(ERR_SEQUENCE_INVALID_STATE,
                  "Takes require the sequence in READY", 409)

    # take_number unique per sequence across all statuses (tier 10)
    for other in store.executions.values():
        if other["sequence_id"] == seq["id"] and other["take_number"] == data["take_number"]:
            raise err(ERR_DUPLICATE_TAKE_NUMBER,
                      "take_number already used by an execution of this sequence", 409)

    if seq["production_id"] != data["production_id"]:
        raise err(ERR_CROSS_PRODUCTION_REFERENCE,
                  "production_id must equal the sequence's production", 422)

    # permit window re-checked at the current logical instant (tier 12)
    now = store.now()
    for pt in required_permit_types(seq):
        covered = any(
            p["production_id"] == prod["id"]
            and p["permit_type"] == pt
            and p["status"] == "GRANTED"
            and p["valid_from"] <= now
            and p["valid_until"] >= now
            for p in store.permits.values()
        )
        if not covered:
            raise err(ERR_PERMIT_MISSING_OR_WINDOW_MISMATCH,
                      f"No GRANTED {pt} permit covers the current instant", 422)
    # equipment currency re-checked at the current instant
    for eid in seq["required_equipment_ids"]:
        item = store.equipment.get(eid)
        if item is None or item["status"] != "IN_SERVICE" or not inspection_current(item):
            raise err(ERR_EQUIPMENT_NOT_READY,
                      "A required equipment item is not IN_SERVICE with a current "
                      "inspection", 422)

    execution = stamp_mutable(
        stamp_new(
            {
                "id": new_id(),
                "production_id": data["production_id"],
                "sequence_id": seq["id"],
                "take_number": data["take_number"],
                "status": "ATTEMPTED",
                "executed_at": now,
                "abort_reason": None,
                "safety_related": False,
            }
        )
    )
    store.executions[execution["id"]] = execution
    touch(seq)  # every take attempt advances the sequence version
    return ok(serialize_execution(execution), 201)


@bp.get("/api/stunt-executions")
def list_executions():
    _, role = auth()
    require_role(role, READ_ROLES)
    limit, offset = pagination_params()
    production_id = request.args.get("production_id")
    sequence_id = request.args.get("sequence_id")
    status = request.args.get("status")
    items = []
    for e in store.executions.values():
        if production_id is not None and e["production_id"] != production_id:
            continue
        if sequence_id is not None and e["sequence_id"] != sequence_id:
            continue
        if status is not None and e["status"] != status:
            continue
        items.append(e)
    items.sort(key=default_sort_key)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize_execution(e) for e in page], total, limit, offset)


@bp.get("/api/stunt-executions/<eid>")
def get_one_execution(eid):
    _, role = auth()
    require_role(role, READ_ROLES)
    execution = get_execution(eid)
    return ok(serialize_execution(execution), 200)


@bp.post("/api/stunt-executions/<eid>/complete")
def complete_execution(eid):
    body = get_body()
    validate_payload(body, {})
    user_id, role = auth()
    require_role(role, COORD)
    execution = get_execution(eid)
    seq = get_sequence(execution["sequence_id"])
    _owner_check(seq, user_id)
    prod = get_production(execution["production_id"])
    gate_posture_active(prod)
    if execution["status"] != "ATTEMPTED":
        raise err(ERR_EXECUTION_INVALID_STATE,
                  "complete requires status ATTEMPTED", 409)

    execution["status"] = "COMPLETED"
    touch(execution)

    completed_count = sum(
        1 for e in store.executions.values()
        if e["sequence_id"] == seq["id"] and e["status"] == "COMPLETED"
    )
    # the first completed take moves READY -> EXECUTED
    if completed_count == 1 and seq["status"] == "READY":
        seq["status"] = "EXECUTED"
        touch(seq)
    # AGREED adjustments accrue the take bonus per actual completed take
    for adj in store.adjustments.values():
        if adj["sequence_id"] == seq["id"] and adj["status"] == "AGREED":
            adj["payable_amount_cents"] = (
                adj["final_amount_cents"] + TAKE_BONUS_CENTS * completed_count
            )
            touch(adj)
    return ok(serialize_execution(execution), 200)


@bp.post("/api/stunt-executions/<eid>/abort")
def abort_execution(eid):
    body = get_body()
    data = validate_payload(
        body,
        {
            "abort_reason": (v_string, True, None),
            "safety_related": (v_bool, True, None),
            "incident_severity": (v_enum(INCIDENT_SEVERITIES), False, None),
        },
    )
    if data["safety_related"] and data["incident_severity"] is None:
        raise err(ERR_VALIDATION,
                  "incident_severity is required when safety_related is true", 400)
    user_id, role = auth()
    require_role(role, COORD)
    execution = get_execution(eid)
    seq = get_sequence(execution["sequence_id"])
    _owner_check(seq, user_id)
    prod = get_production(execution["production_id"])
    gate_posture_active(prod)
    if execution["status"] != "ATTEMPTED":
        raise err(ERR_EXECUTION_INVALID_STATE,
                  "abort requires status ATTEMPTED", 409)

    execution["status"] = "ABORTED"
    execution["abort_reason"] = data["abort_reason"]
    execution["safety_related"] = data["safety_related"]
    touch(execution)

    if data["safety_related"]:
        # auto-create the incident; SERIOUS/CRITICAL fires the stoppage cascade
        create_incident_record(
            prod["id"],
            seq["id"],
            data["incident_severity"],
            store.now(),
            data["abort_reason"],
            user_id,
        )
    return ok(serialize_execution(execution), 200)
