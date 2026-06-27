import re
from flask import Blueprint

import core
from core import (store, require, get_body, get_or_404, ok, ok_list, paginate, common_create, touch,
                  req_str, req_enum, req_int, req_number, opt_bool, ApiError,
                  ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_DUPLICATE_CULTIVAR, ERR_VARIETY_IN_USE)

bp = Blueprint("varieties", __name__)

ALL_ROLES = ["GrowerManager", "ProductionTech", "SalesCoordinator", "Broker"]
PROP_FORMS = {"PLUG", "LINER", "BARE_ROOT"}
IN_USE_STATES = {"PLANNED", "GROWING", "GRADING", "SALEABLE", "HELD"}


def _cultivar_in_use(code, exclude_id=None):
    for v in store.varieties.values():
        if v["id"] == exclude_id:
            continue
        if v["status"] != "RETIRED" and v["cultivar_code"] == code:
            return True
    return False


@bp.post("/nursery/varieties")
def create_variety():
    require(["GrowerManager"])
    body = get_body()
    common_name = req_str(body, "common_name")
    cultivar_code = req_str(body, "cultivar_code")
    if not re.fullmatch(r"[A-Z0-9]+", cultivar_code):
        raise ApiError(ERR_INVALID_REQUEST, "cultivar_code must be uppercase alphanumeric")
    propagation_form = req_enum(body, "propagation_form", PROP_FORMS)
    grow_cycle_days = req_int(body, "grow_cycle_days", minimum=1)
    container_footprint_units = req_int(body, "container_footprint_units", minimum=1)
    ship_ready_grade_min_height_cm = req_number(body, "ship_ready_grade_min_height_cm", exclusive_min=0)
    ship_ready_min_live_pct = req_number(body, "ship_ready_min_live_pct", exclusive_min=0, maximum=1)
    requires_phyto = opt_bool(body, "requires_phyto", False)
    v = common_create({
        "common_name": common_name,
        "cultivar_code": cultivar_code,
        "propagation_form": propagation_form,
        "grow_cycle_days": grow_cycle_days,
        "container_footprint_units": container_footprint_units,
        "ship_ready_grade_min_height_cm": ship_ready_grade_min_height_cm,
        "ship_ready_min_live_pct": ship_ready_min_live_pct,
        "requires_phyto": requires_phyto,
        "status": "DRAFT",
    })
    store.varieties[v["id"]] = v
    return ok(v, 201)


@bp.get("/nursery/varieties/<vid>")
def get_variety(vid):
    require(ALL_ROLES)
    v = get_or_404(store.varieties, vid)
    return ok(v)


@bp.get("/nursery/varieties")
def list_varieties():
    require(ALL_ROLES)
    from flask import request
    rows = list(store.varieties.values())
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)


@bp.post("/nursery/varieties/<vid>/activate")
def activate_variety(vid):
    require(["GrowerManager"])
    v = get_or_404(store.varieties, vid)
    if v["status"] not in ("DRAFT", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, "Variety cannot be activated from %s" % v["status"])
    if _cultivar_in_use(v["cultivar_code"], exclude_id=v["id"]):
        raise ApiError(ERR_DUPLICATE_CULTIVAR, "cultivar_code already used by a non-retired variety")
    v["status"] = "ACTIVE"
    touch(v)
    return ok(v)


@bp.post("/nursery/varieties/<vid>/suspend")
def suspend_variety(vid):
    require(["GrowerManager"])
    v = get_or_404(store.varieties, vid)
    if v["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Variety cannot be suspended from %s" % v["status"])
    v["status"] = "SUSPENDED"
    touch(v)
    return ok(v)


@bp.post("/nursery/varieties/<vid>/retire")
def retire_variety(vid):
    require(["GrowerManager"])
    v = get_or_404(store.varieties, vid)
    if v["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, "Variety cannot be retired from %s" % v["status"])
    for b in store.batches.values():
        if b["variety_id"] == v["id"] and b["status"] in IN_USE_STATES:
            raise ApiError(ERR_VARIETY_IN_USE, "Variety still backs a non-terminal batch")
    v["status"] = "RETIRED"
    touch(v)
    return ok(v)
