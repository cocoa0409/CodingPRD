"""Design consults, space measures, component configs."""
from flask import Blueprint, request

import db
import serialize
from errors import err
from response import object_response, array_response
from middleware import get_identity, require_roles
from validate import (get_body, require_str, require_enum, require_int,
                      require_number, require_datetime, parse_pagination,
                      paginate)
from services import calc

bp = Blueprint("design", __name__)

MATERIAL_GRADES = {"MELAMINE", "LAMINATE", "WOOD", "PREMIUM_WOOD"}
COMPONENT_TYPES = {"SHELF", "DRAWER", "ROD", "CABINET", "PANEL", "ACCESSORY"}


def _require_project(pid):
    rec = db.projects.get(pid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    return rec


# ---------------- Design consults ----------------
@bp.post("/projects/<pid>/design-consults")
def create_consult(pid):
    _, role = get_identity()
    require_roles(role, {"Designer"})
    project = _require_project(pid)
    body = get_body()
    designer_user_id = require_str(body, "designer_user_id")
    start = require_datetime(body, "scheduled_start")
    end = require_datetime(body, "scheduled_end")
    if not (end > start):
        raise err("ERR_VALIDATION", "scheduled_end must be after scheduled_start.")

    is_first = not any(c["project_id"] == pid for c in db.design_consults.values())

    rec = db.stamp_new({
        "project_id": pid,
        "designer_user_id": designer_user_id,
        "scheduled_start": start,
        "scheduled_end": end,
        "status": "SCHEDULED",
        "rendering_url": None,
    })
    db.design_consults[rec["id"]] = rec

    # First consult on a LEAD project advances it to DESIGNING.
    if is_first and project["status"] == "LEAD":
        project["status"] = "DESIGNING"
        db.touch(project)
    return object_response(serialize.design_consult(rec), 201)


@bp.get("/projects/<pid>/design-consults")
def list_consults(pid):
    _, role = get_identity()
    require_roles(role, {"Customer", "Designer", "PlatformAdmin"})
    _require_project(pid)
    limit, offset = parse_pagination()
    items = [c for c in db.design_consults.values() if c["project_id"] == pid]
    page, total = paginate(items, limit, offset)
    return array_response([serialize.design_consult(c) for c in page],
                          limit, offset, total)


def _require_consult(cid):
    rec = db.design_consults.get(cid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    return rec


@bp.post("/design-consults/<cid>/render")
def render_consult(cid):
    _, role = get_identity()
    require_roles(role, {"Designer"})
    rec = _require_consult(cid)
    if rec["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE")
    body = get_body()
    rendering_url = require_str(body, "rendering_url")
    rec["rendering_url"] = rendering_url
    rec["status"] = "RENDERED"
    db.touch(rec)
    return object_response(serialize.design_consult(rec))


@bp.post("/design-consults/<cid>/complete")
def complete_consult(cid):
    _, role = get_identity()
    require_roles(role, {"Designer"})
    rec = _require_consult(cid)
    if rec["status"] != "RENDERED":
        raise err("ERR_INVALID_STATE")
    rec["status"] = "COMPLETED"
    db.touch(rec)
    return object_response(serialize.design_consult(rec))


@bp.post("/design-consults/<cid>/cancel")
def cancel_consult(cid):
    _, role = get_identity()
    require_roles(role, {"Designer"})
    rec = _require_consult(cid)
    if rec["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE")
    rec["status"] = "CANCELLED"
    db.touch(rec)
    return object_response(serialize.design_consult(rec))


# ---------------- Space measures ----------------
@bp.post("/projects/<pid>/space-measures")
def create_measure(pid):
    _, role = get_identity()
    require_roles(role, {"Designer"})
    _require_project(pid)
    body = get_body()
    wall_count = require_int(body, "wall_count", minimum=1)
    linear_feet = require_number(body, "linear_feet", minimum=0, strict=True)
    ceiling_height_in = require_number(body, "ceiling_height_in", minimum=84)
    rec = db.stamp_new({
        "project_id": pid,
        "wall_count": wall_count,
        "linear_feet": linear_feet,
        "ceiling_height_in": ceiling_height_in,
        "confirmed": False,
    })
    db.space_measures[rec["id"]] = rec
    return object_response(serialize.space_measure(rec), 201)


@bp.get("/projects/<pid>/space-measures")
def list_measures(pid):
    _, role = get_identity()
    require_roles(role, {"Customer", "Designer", "PlatformAdmin"})
    _require_project(pid)
    limit, offset = parse_pagination()
    items = [m for m in db.space_measures.values() if m["project_id"] == pid]
    page, total = paginate(items, limit, offset)
    return array_response([serialize.space_measure(m) for m in page],
                          limit, offset, total)


# ---------------- Component configs ----------------
def _validate_line_items(body):
    # PRD 3.2 requires line_items to be an array and constrains each item, but
    # the non-empty requirement applies only at finalize, not at creation. A
    # DRAFT config may be created with an empty line_items array.
    line_items = body.get("line_items")
    if not isinstance(line_items, list):
        raise err("ERR_VALIDATION", "line_items must be an array.")
    out = []
    for li in line_items:
        if not isinstance(li, dict):
            raise err("ERR_VALIDATION", "each line item must be an object.")
        ctype = li.get("component_type")
        if ctype not in COMPONENT_TYPES:
            raise err("ERR_VALIDATION", "invalid component_type.")
        qty = li.get("quantity")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise err("ERR_VALIDATION", "quantity must be an integer >= 1.")
        unit = li.get("unit_price_cents")
        if isinstance(unit, bool) or not isinstance(unit, int) or unit < 0:
            raise err("ERR_VALIDATION", "unit_price_cents must be an integer >= 0.")
        out.append({
            "component_type": ctype,
            "quantity": qty,
            "unit_price_cents": unit,
        })
    return out


@bp.post("/projects/<pid>/component-configs")
def create_config(pid):
    _, role = get_identity()
    require_roles(role, {"Designer"})
    _require_project(pid)
    body = get_body()
    space_measure_id = require_str(body, "space_measure_id")
    material_grade = require_enum(body, "material_grade", MATERIAL_GRADES)
    line_items = _validate_line_items(body)
    measure = db.space_measures.get(space_measure_id)
    if measure is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    rec = db.stamp_new({
        "project_id": pid,
        "space_measure_id": space_measure_id,
        "material_grade": material_grade,
        "line_items": line_items,
        "status": "DRAFT",
        "total_units": 0,
    })
    db.component_configs[rec["id"]] = rec
    return object_response(serialize.component_config(rec), 201)


@bp.get("/projects/<pid>/component-configs")
def list_configs(pid):
    _, role = get_identity()
    require_roles(role, {"Customer", "Designer", "PlatformAdmin"})
    _require_project(pid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [c for c in db.component_configs.values()
             if c["project_id"] == pid and (status is None or c["status"] == status)]
    page, total = paginate(items, limit, offset)
    return array_response([serialize.component_config(c) for c in page],
                          limit, offset, total)


@bp.get("/component-configs/<cid>")
def get_config(cid):
    _, role = get_identity()
    require_roles(role, {"Customer", "Designer", "PlatformAdmin"})
    rec = db.component_configs.get(cid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    return object_response(serialize.component_config(rec))


@bp.get("/component-configs")
def list_configs_global():
    _, role = get_identity()
    require_roles(role, {"Designer", "PlatformAdmin"})
    limit, offset = parse_pagination()
    space_measure_id = request.args.get("space_measure_id")
    items = [c for c in db.component_configs.values()
             if space_measure_id is None or c["space_measure_id"] == space_measure_id]
    page, total = paginate(items, limit, offset)
    return array_response([serialize.component_config(c) for c in page],
                          limit, offset, total)


@bp.post("/component-configs/<cid>/finalize")
def finalize_config(cid):
    _, role = get_identity()
    require_roles(role, {"Designer"})
    rec = db.component_configs.get(cid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    if rec["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE")
    if not rec["line_items"]:
        raise err("ERR_VALIDATION", "line_items must be non-empty.")
    measure = db.space_measures.get(rec["space_measure_id"])
    if measure is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    if measure["confirmed"]:
        raise err("ERR_MEASURE_ALREADY_CONFIRMED")
    rec["total_units"] = calc.config_total_units(rec["line_items"])
    rec["status"] = "FINALIZED"
    db.touch(rec)
    measure["confirmed"] = True
    db.touch(measure)
    return object_response(serialize.component_config(rec))
