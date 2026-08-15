"""ProductionLine endpoints."""
from flask import Blueprint

import domain as D
from db import store, mint, touch
from errors import err
from middleware import authorize, ROLES
from response import ok, ok_list
from validate import body, need_str, need_int, need_enum, paginate

bp = Blueprint("lines", __name__)


@bp.post("/plant/lines")
def create_line():
    authorize(["PlantManager"])
    b = body()
    line_code = need_str(b, "line_code")
    allergen_zone = need_enum(b, "allergen_zone", D.ALLERGEN_ZONES)
    cases_per_hour = need_int(b, "cases_per_hour")
    if cases_per_hour <= 0:
        err("ERR_INVALID_REQUEST", 400, "cases_per_hour must be greater than zero")
    for l in store.lines.values():
        if l["line_code"] == line_code:
            err("ERR_DUPLICATE_CODE", 409, "line_code already exists")
    line = mint()
    line.update({"line_code": line_code, "allergen_zone": allergen_zone,
                 "cases_per_hour": cases_per_hour, "current_product_id": None,
                 "line_status": "ACTIVE"})
    store.lines[line["id"]] = line
    return ok(D.line_json(line), 201)


@bp.get("/plant/lines")
def list_lines():
    authorize(ROLES)
    page, limit, offset, total = paginate(list(store.lines.values()), D.line_json)
    return ok_list(page, limit, offset, total)


@bp.get("/plant/lines/<lid>")
def get_line(lid):
    authorize(ROLES)
    return ok(D.line_json(D.get_line(lid)))


@bp.post("/plant/lines/<lid>/set-status")
def set_line_status(lid):
    authorize(["PlantManager"])
    b = body()
    line_status = need_enum(b, "line_status", D.LINE_STATUSES)
    line = D.get_line(lid)
    if line_status == "DOWN":
        for r in store.runs.values():
            if r["line_id"] == lid and r["production_status"] == "IN_PROGRESS":
                err("ERR_RUN_INVALID_STATE", 409,
                    "Line cannot go DOWN while a run is IN_PROGRESS")
    line["line_status"] = line_status
    touch(line)
    return ok(D.line_json(line))


@bp.get("/plant/lines/<lid>/runs")
def line_runs(lid):
    authorize(ROLES)
    D.get_line(lid)
    items = [r for r in store.runs.values() if r["line_id"] == lid]
    page, limit, offset, total = paginate(items, D.run_json)
    return ok_list(page, limit, offset, total)


@bp.get("/plant/lines/<lid>/changeovers")
def line_changeovers(lid):
    authorize(ROLES)
    D.get_line(lid)
    items = [c for c in store.changeovers.values() if c["line_id"] == lid]
    page, limit, offset, total = paginate(items, D.changeover_json)
    return ok_list(page, limit, offset, total)
