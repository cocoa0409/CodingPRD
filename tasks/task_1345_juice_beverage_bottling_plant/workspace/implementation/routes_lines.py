"""BottlingLine endpoints."""
from flask import Blueprint

from domain import CONTAINER_TYPES, ser_line, ser_run
from errors import err
from store import db, stamp, touch
from util import body, ok, paginate, req_enum_list, req_field, require_any, require_roles

bp = Blueprint("lines", __name__)


def get_line_or_404(line_id):
    line = db.lines.get(line_id)
    if line is None:
        raise err("ERR_LINE_NOT_FOUND", f"BottlingLine {line_id} not found")
    return line


@bp.post("/v1/bottling-lines")
def create_line():
    require_roles("PlantManager")
    data = body()
    line_code = req_field(data, "line_code", "str")
    supported = req_enum_list(data, "supported_container_types", CONTAINER_TYPES)
    nominal_cpm = req_field(data, "nominal_cpm", "int")
    line = {
        "line_code": line_code,
        "supported_container_types": supported,
        "nominal_cpm": nominal_cpm,
        "status": "ACTIVE",
    }
    stamp(line)
    db.lines[line["id"]] = line
    return ok(ser_line(line), 201)


@bp.get("/v1/bottling-lines")
def list_lines():
    require_any()
    return paginate(list(db.lines.values()), ser_line)


@bp.get("/v1/bottling-lines/<line_id>")
def get_line(line_id):
    require_any()
    return ok(ser_line(get_line_or_404(line_id)))


@bp.post("/v1/bottling-lines/<line_id>/set-maintenance")
def set_maintenance(line_id):
    require_roles("PlantManager")
    line = get_line_or_404(line_id)
    if line["status"] != "ACTIVE":
        raise err("ERR_LINE_STATE_INVALID", "set-maintenance requires status ACTIVE")
    for run in db.runs.values():
        if run.get("line_id") == line_id and run["production_status"] in ("SCHEDULED", "IN_PRODUCTION"):
            raise err("ERR_LINE_STATE_INVALID",
                      "Line has runs in SCHEDULED or IN_PRODUCTION")
    line["status"] = "MAINTENANCE"
    touch(line)
    return ok(ser_line(line))


@bp.post("/v1/bottling-lines/<line_id>/set-active")
def set_active(line_id):
    require_roles("PlantManager")
    line = get_line_or_404(line_id)
    if line["status"] != "MAINTENANCE":
        raise err("ERR_LINE_STATE_INVALID", "set-active requires status MAINTENANCE")
    line["status"] = "ACTIVE"
    touch(line)
    return ok(ser_line(line))


@bp.get("/v1/bottling-lines/<line_id>/production-runs")
def line_runs(line_id):
    require_any()
    get_line_or_404(line_id)
    items = [r for r in db.runs.values() if r.get("line_id") == line_id]
    return paginate(items, ser_run)
