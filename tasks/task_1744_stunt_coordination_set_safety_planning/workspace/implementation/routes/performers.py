"""StuntPerformer: register, suspend, reinstate."""

from flask import Blueprint, request

from db import store
from domain import (
    get_production,
    get_performer,
    gate_posture_setup_or_active,
    performer_effective_status,
    performer_has_valid_cert,
    serialize_performer,
    stamp_new,
    stamp_mutable,
    touch,
    UNION_STATUSES,
    default_sort_key,
)
from errors import err, ERR_PERFORMER_NOT_QUALIFIED, ERR_NO_VALID_CERTIFICATION
from middleware import (
    auth,
    require_role,
    get_body,
    validate_payload,
    pagination_params,
    v_string,
    v_nonempty_string,
    v_pos_int,
    v_enum,
)
from response import ok, ok_list
from util import new_id

bp = Blueprint("performers", __name__)

READ_ROLES = ["ProductionExecutive", "StuntCoordinator", "SafetyOfficer",
              "DepartmentHead", "Performer", "EquipmentInspector"]


@bp.post("/api/performers")
def create_performer():
    body = get_body()
    data = validate_payload(
        body,
        {
            "production_id": (v_string, True, None),
            "first_name": (v_string, True, None),
            "last_name": (v_string, True, None),
            "base_day_rate_cents": (v_pos_int, True, None),
            "union_status": (v_enum(UNION_STATUSES), True, None),
        },
    )
    _, role = auth()
    require_role(role, ["StuntCoordinator"])
    prod = get_production(data["production_id"])
    gate_posture_setup_or_active(prod)

    performer = stamp_mutable(
        stamp_new(
            {
                "id": new_id(),
                "production_id": prod["id"],
                "first_name": data["first_name"],
                "last_name": data["last_name"],
                "base_day_rate_cents": data["base_day_rate_cents"],
                "union_status": data["union_status"],
                "status": "REGISTERED",
                "completed_rehearsal_minutes": 0,
            }
        )
    )
    store.performers[performer["id"]] = performer
    return ok(serialize_performer(performer), 201)


@bp.get("/api/performers")
def list_performers():
    _, role = auth()
    require_role(role, READ_ROLES)
    limit, offset = pagination_params()
    production_id = request.args.get("production_id")
    status = request.args.get("status")
    items = []
    for p in store.performers.values():
        if production_id is not None and p["production_id"] != production_id:
            continue
        if status is not None and performer_effective_status(p) != status:
            continue
        items.append(p)
    items.sort(key=default_sort_key)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize_performer(p) for p in page], total, limit, offset)


@bp.get("/api/performers/<pid>")
def get_one_performer(pid):
    _, role = auth()
    require_role(role, READ_ROLES)
    performer = get_performer(pid)
    return ok(serialize_performer(performer), 200)


@bp.post("/api/performers/<pid>/suspend")
def suspend_performer(pid):
    body = get_body()
    validate_payload(body, {"reason": (v_nonempty_string, True, None)})
    _, role = auth()
    require_role(role, ["SafetyOfficer"])
    performer = get_performer(pid)
    if performer_effective_status(performer) != "QUALIFIED":
        raise err(ERR_PERFORMER_NOT_QUALIFIED,
                  "suspend requires performer status QUALIFIED", 409)
    performer["status"] = "SUSPENDED"
    touch(performer)
    return ok(serialize_performer(performer), 200)


@bp.post("/api/performers/<pid>/reinstate")
def reinstate_performer(pid):
    body = get_body()
    validate_payload(body, {})
    _, role = auth()
    require_role(role, ["SafetyOfficer"])
    performer = get_performer(pid)
    if performer["status"] != "SUSPENDED":
        raise err(ERR_PERFORMER_NOT_QUALIFIED,
                  "reinstate requires performer status SUSPENDED", 409)
    if not performer_has_valid_cert(performer["id"], store.now()):
        raise err(ERR_NO_VALID_CERTIFICATION,
                  "reinstate requires at least one valid certification", 409)
    performer["status"] = "QUALIFIED"
    touch(performer)
    return ok(serialize_performer(performer), 200)
