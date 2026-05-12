"""ValveGroup routes."""

from flask import Blueprint, g

from db import DB, LOCK, new_id
from errors import forbidden, valve_group_invalid, validation_error
from middleware import require_roles
from response import success_object
from services.common import (
    bump_version,
    check_occ,
    fetch_or_404,
    get_json_body,
    require_str,
    stamp_create,
)
from services.serializers import valve_group_view


bp = Blueprint("valve_groups", __name__)


VALID_CONTROL_MODES = {"SEQUENTIAL", "PARALLEL"}


def _validate_valve_group_payload(*, valve_ids, control_mode, max_parallel_valves):
    if not isinstance(valve_ids, list) or len(valve_ids) == 0:
        raise valve_group_invalid("valve_ids must be a non-empty array")
    if len(valve_ids) > 16:
        raise valve_group_invalid("valve_ids exceeds max length 16")
    for v in valve_ids:
        if not isinstance(v, str) or not v.strip():
            raise valve_group_invalid("valve_ids must contain non-empty strings")
    if control_mode not in VALID_CONTROL_MODES:
        raise valve_group_invalid("control_mode invalid")
    if isinstance(max_parallel_valves, bool) or not isinstance(max_parallel_valves, int):
        raise valve_group_invalid("max_parallel_valves must be an integer")
    if max_parallel_valves < 1:
        raise valve_group_invalid("max_parallel_valves must be >= 1")
    if control_mode == "SEQUENTIAL" and max_parallel_valves != 1:
        raise valve_group_invalid("SEQUENTIAL requires max_parallel_valves == 1")


@bp.route("/valve-groups", methods=["POST"])
@require_roles("WaterAdmin")
def create_valve_group():
    body = get_json_body()
    tenant_id = require_str(body, "tenant_id")
    name = require_str(body, "name")
    pump_id = require_str(body, "pump_id")
    if "valve_ids" not in body:
        raise validation_error("valve_ids is required")
    if "control_mode" not in body:
        raise validation_error("control_mode is required")
    valve_ids = body["valve_ids"]
    control_mode = body["control_mode"]
    max_parallel = body.get("max_parallel_valves")
    if max_parallel is None:
        max_parallel = 1 if control_mode == "SEQUENTIAL" else 1

    _validate_valve_group_payload(
        valve_ids=valve_ids,
        control_mode=control_mode,
        max_parallel_valves=max_parallel,
    )
    with LOCK:
        if tenant_id not in DB.tenants:
            raise validation_error("tenant_id does not exist")
        rec = stamp_create({
            "id": new_id(),
            "tenant_id": tenant_id,
            "name": name,
            "pump_id": pump_id,
            "valve_ids": list(valve_ids),
            "control_mode": control_mode,
            "max_parallel_valves": int(max_parallel),
        })
        DB.valve_groups[rec["id"]] = rec
    return success_object(valve_group_view(rec), status=201)


@bp.route("/valve-groups/<valve_group_id>", methods=["GET"])
def read_valve_group(valve_group_id):
    if g.role not in {"PlatformAdmin", "WaterAdmin", "Operator"}:
        raise forbidden()
    with LOCK:
        rec = fetch_or_404(DB.valve_groups, valve_group_id)
    return success_object(valve_group_view(rec))


@bp.route("/valve-groups/<valve_group_id>", methods=["PATCH"])
@require_roles("WaterAdmin")
def update_valve_group(valve_group_id):
    body = get_json_body()
    with LOCK:
        rec = fetch_or_404(DB.valve_groups, valve_group_id)
        check_occ(rec, body)

        new_name = body.get("name", rec.get("name"))
        new_valve_ids = body.get("valve_ids", rec.get("valve_ids"))
        new_mode = body.get("control_mode", rec.get("control_mode"))
        new_max = body.get("max_parallel_valves", rec.get("max_parallel_valves"))

        _validate_valve_group_payload(
            valve_ids=new_valve_ids,
            control_mode=new_mode,
            max_parallel_valves=new_max,
        )

        if new_name is not None:
            if not isinstance(new_name, str) or not new_name.strip():
                raise validation_error("name must be non-empty string")
            rec["name"] = new_name
        rec["valve_ids"] = list(new_valve_ids)
        rec["control_mode"] = new_mode
        rec["max_parallel_valves"] = int(new_max)
        bump_version(rec)
    return success_object(valve_group_view(rec))
