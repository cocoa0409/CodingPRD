"""Inspector endpoints."""
from flask import Blueprint

import serial
import services
from core import (db, ensure_object, filter_str, get_body, mark, ok, ok_list,
                  opt_enum, opt_int, ordered, paginate, req_int, req_str,
                  require_auth, resolve_path, stamp_new)
from guards import ADMIN, ADMIN_ANALYST, check_state_code

bp = Blueprint("inspectors", __name__)

INSPECTOR_STATUSES = ("ACTIVE", "INACTIVE")


@bp.post("/inspectors")
def create_inspector():
    require_auth(ADMIN)
    body = get_body()
    ensure_object(body)
    full_name = req_str(body, "full_name")
    state_code = check_state_code(req_str(body, "state_code"))
    max_daily_minutes = req_int(body, "max_daily_minutes", minimum=60)
    status = opt_enum(body, "status", INSPECTOR_STATUSES, default="ACTIVE")
    row = stamp_new({
        "full_name": full_name,
        "state_code": state_code,
        "max_daily_minutes": max_daily_minutes,
        "committed_minutes": 0,
        "status": status,
    })
    db.inspectors[row["id"]] = row
    return ok(serial.inspector(row), 201)


@bp.get("/inspectors/<inspector_id>")
def get_inspector(inspector_id):
    require_auth(("FnsAdmin", "FnsAnalyst", "Inspector"))
    row = resolve_path(db.inspectors, inspector_id, "ERR_INSPECTOR_NOT_FOUND")
    return ok(serial.inspector(row))


@bp.get("/inspectors")
def list_inspectors():
    require_auth(ADMIN_ANALYST)
    rows = ordered(list(db.inspectors.values()))
    for name in ("state_code", "status"):
        value = filter_str(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    data, pagination = paginate(rows, serial.inspector)
    return ok_list(data, pagination)


@bp.patch("/inspectors/<inspector_id>")
def patch_inspector(inspector_id):
    require_auth(ADMIN)
    row = resolve_path(db.inspectors, inspector_id, "ERR_INSPECTOR_NOT_FOUND")
    body = get_body()
    ensure_object(body)
    status = opt_enum(body, "status", INSPECTOR_STATUSES)
    max_daily_minutes = opt_int(body, "max_daily_minutes", minimum=60)
    if status is not None:
        row["status"] = status
    if max_daily_minutes is not None:
        row["max_daily_minutes"] = max_daily_minutes
    mark(row)
    services.commit()
    return ok(serial.inspector(row))
