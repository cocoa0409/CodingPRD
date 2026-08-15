"""Customers, CoatingSpecs, PaintLines, CureOvens."""
from db import STORE
from errors import ApiError
from middleware import require_roles, ROLES
from response import success_object, success_list, paginate
from serializers import ser_customer, ser_spec, ser_paint_line, ser_cure_oven, ser_stage
from services import new_common, touch
from validators import get_body, req, as_str, as_int, as_num

from . import bp

ALLOCATION_POLICIES = ("FULL_TO_NEXT_LOT", "PRO_RATA_BY_PARTS")


def _get_or_404(table, rid):
    rec = STORE[table].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found: %s" % rid)
    return rec


# --- Customer ----------------------------------------------------------------

@bp.post("/ecoat/customers")
@require_roles("PlantAdmin")
def create_customer():
    body = get_body()
    name = as_str(req(body, "name"), "name")
    c = new_common()
    c.update({"name": name})
    STORE["customers"][c["id"]] = c
    return success_object(ser_customer(c), 201)


@bp.get("/ecoat/customers/<cid>")
@require_roles(*ROLES)
def get_customer(cid):
    return success_object(ser_customer(_get_or_404("customers", cid)))


# --- CoatingSpec -------------------------------------------------------------

@bp.post("/ecoat/coating-specs")
@require_roles("PlantAdmin")
def create_spec():
    body = get_body()
    customer_id = as_str(req(body, "customer_id"), "customer_id")
    color_code = as_str(req(body, "color_code"), "color_code")
    fmin = as_num(req(body, "film_build_min_um"), "film_build_min_um")
    fmax = as_num(req(body, "film_build_max_um"), "film_build_max_um")
    cure_temp = as_num(req(body, "cure_metal_temp_c"), "cure_metal_temp_c")
    cure_minutes = as_int(req(body, "cure_minutes_at_temp"), "cure_minutes_at_temp")
    adhesion_min = as_int(req(body, "adhesion_class_min"), "adhesion_class_min")
    if not (0 <= adhesion_min <= 5):
        raise ApiError("ERR_INVALID_REQUEST", 400, "adhesion_class_min must be an integer 0-5")
    impact_min = as_num(req(body, "impact_joules_min"), "impact_joules_min")
    voc = as_num(req(body, "voc_g_per_l"), "voc_g_per_l")
    area = as_num(req(body, "area_dm2_per_part"), "area_dm2_per_part")

    if STORE["customers"].get(customer_id) is None:
        raise ApiError("ERR_NOT_FOUND", 404, "customer_id does not exist")

    # At most one ACTIVE spec per (customer_id, color_code): supersede the prior.
    for s in STORE["coating_specs"].values():
        if (s["customer_id"] == customer_id and s["color_code"] == color_code
                and s["status"] == "ACTIVE"):
            s["status"] = "SUPERSEDED"
            touch(s)

    sp = new_common()
    sp.update({
        "customer_id": customer_id, "color_code": color_code,
        "film_build_min_um": fmin, "film_build_max_um": fmax,
        "cure_metal_temp_c": cure_temp, "cure_minutes_at_temp": cure_minutes,
        "adhesion_class_min": adhesion_min, "impact_joules_min": impact_min,
        "voc_g_per_l": voc, "area_dm2_per_part": area,
        "status": "ACTIVE",
    })
    STORE["coating_specs"][sp["id"]] = sp
    return success_object(ser_spec(sp), 201)


@bp.get("/ecoat/coating-specs/<sid>")
@require_roles(*ROLES)
def get_spec(sid):
    return success_object(ser_spec(_get_or_404("coating_specs", sid)))


@bp.get("/ecoat/coating-specs")
@require_roles(*ROLES)
def list_specs():
    from flask import request
    items = list(STORE["coating_specs"].values())
    customer_id = request.args.get("customer_id")
    color_code = request.args.get("color_code")
    if customer_id is not None:
        items = [s for s in items if s["customer_id"] == customer_id]
    if color_code is not None:
        items = [s for s in items if s["color_code"] == color_code]
    page, meta = paginate(items, ser_spec)
    return success_list(page, meta)


# --- PaintLine ---------------------------------------------------------------

@bp.post("/ecoat/paint-lines")
@require_roles("PlantAdmin")
def create_paint_line():
    body = get_body()
    name = as_str(req(body, "name"), "name")
    color = as_str(req(body, "current_color_code"), "current_color_code")
    speed = as_num(req(body, "line_speed_fpm"), "line_speed_fpm")
    if speed <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "line_speed_fpm must be positive")
    capacity = as_int(req(body, "hanger_capacity_parts"), "hanger_capacity_parts")
    policy = req(body, "allocation_policy")
    if policy not in ALLOCATION_POLICIES:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "allocation_policy must be one of %s" % (", ".join(ALLOCATION_POLICIES)))
    line = new_common()
    line.update({
        "name": name, "current_color_code": color, "line_speed_fpm": speed,
        "hanger_capacity_parts": capacity, "allocation_policy": policy,
        "posture": "RUNNING",
    })
    STORE["paint_lines"][line["id"]] = line
    return success_object(ser_paint_line(line), 201)


@bp.get("/ecoat/paint-lines/<lid>")
@require_roles(*ROLES)
def get_paint_line(lid):
    return success_object(ser_paint_line(_get_or_404("paint_lines", lid)))


@bp.post("/ecoat/paint-lines/<lid>/set-line-speed")
@require_roles("LineScheduler")
def set_line_speed(lid):
    body = get_body()
    speed = as_num(req(body, "line_speed_fpm"), "line_speed_fpm")
    if speed <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "line_speed_fpm must be positive")
    line = _get_or_404("paint_lines", lid)
    # Rejected while a run slot of this line is RUNNING.
    if any(s["paint_line_id"] == lid and s["status"] == "RUNNING"
           for s in STORE["run_slots"].values()):
        raise ApiError("ERR_LINE_BUSY", 409,
                       "Cannot change line speed while a run slot is RUNNING on the line")
    line["line_speed_fpm"] = speed
    touch(line)
    return success_object(ser_paint_line(line))


@bp.get("/ecoat/paint-lines/<lid>/pretreatment-stages")
@require_roles(*ROLES)
def list_line_stages(lid):
    _get_or_404("paint_lines", lid)
    items = [s for s in STORE["pretreatment_stages"].values() if s["paint_line_id"] == lid]
    page, meta = paginate(items, ser_stage)
    return success_list(page, meta)


# --- CureOven ----------------------------------------------------------------

@bp.post("/ecoat/cure-ovens")
@require_roles("PlantAdmin")
def create_cure_oven():
    body = get_body()
    name = as_str(req(body, "name"), "name")
    max_loads = as_int(req(body, "max_loads"), "max_loads")
    oven = new_common()
    oven.update({"name": name, "max_loads": max_loads})
    STORE["cure_ovens"][oven["id"]] = oven
    return success_object(ser_cure_oven(oven), 201)


@bp.get("/ecoat/cure-ovens/<oid>")
@require_roles(*ROLES)
def get_cure_oven(oid):
    return success_object(ser_cure_oven(_get_or_404("cure_ovens", oid)))
