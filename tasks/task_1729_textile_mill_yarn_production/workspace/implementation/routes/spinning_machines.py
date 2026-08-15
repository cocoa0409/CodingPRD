"""SpinningMachine endpoints."""

from flask import Blueprint, request

from db import db, new_id, now_iso
from errors import err_duplicate_key, err_invalid_request, err_not_found
from middleware import require_roles
from response import success_list, success_object
from serializers import serialize_spinning_machine
from validators import (
    apply_filters,
    get_json_body,
    get_pagination,
    req_decimal,
    req_string,
    sort_and_paginate,
)

bp = Blueprint("spinning_machines", __name__)

READ_ROLES = ("MillPlanner", "SpinningSupervisor", "MillAdmin")


@bp.post("/mill/spinning-machines")
def create_machine():
    require_roles("MillAdmin")
    body = get_json_body()
    machine_code = req_string(body, "machine_code")
    min_ne = req_decimal(body, "supported_count_min_ne", min_value=0, min_exclusive=True)
    max_ne = req_decimal(body, "supported_count_max_ne", min_value=0, min_exclusive=True)
    if max_ne <= min_ne:
        raise err_invalid_request("supported_count_max_ne must be > supported_count_min_ne")

    # Uniqueness on machine_code
    for m in db.spinning_machines.values():
        if m["machine_code"] == machine_code:
            raise err_duplicate_key("machine_code already registered")

    ts = now_iso()
    record = {
        "id": new_id(),
        "machine_code": machine_code,
        "supported_count_min_ne": min_ne,
        "supported_count_max_ne": max_ne,
        "status": "ACTIVE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.spinning_machines[record["id"]] = record
    return success_object(serialize_spinning_machine(record), 201)


@bp.get("/mill/spinning-machines")
def list_machines():
    require_roles(*READ_ROLES)
    limit, offset = get_pagination()
    items = apply_filters(list(db.spinning_machines.values()), {"status": request.args.get("status")})
    page, total = sort_and_paginate(items, limit, offset)
    return success_list([serialize_spinning_machine(r) for r in page], limit, offset, total)


@bp.get("/mill/spinning-machines/<mid>")
def get_machine(mid):
    require_roles(*READ_ROLES)
    record = db.spinning_machines.get(mid)
    if record is None:
        raise err_not_found("Spinning machine not found")
    return success_object(serialize_spinning_machine(record))
