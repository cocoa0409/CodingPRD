"""Routes: production waves, IG units (advance / qc / breakage)."""
from flask import Blueprint, request

from common import (ANY_ROLE, ApiError, D, body_json, err400, list_response, need,
                    obj_response, paginate, require_roles, v_dt, v_enum, v_int, v_num,
                    v_str)
from services import (MANUAL_BREAK_CAUSES, break_unit, certified_u_factor,
                      get_or_404, label_of_line, line_completion_check, lines_of_order,
                      live_lines, ser_ig, ser_wave, transition_line, transition_order,
                      wave_allocation, wave_recompute)
from store import STORE, new_entity, touch

bp_production = Blueprint("production", __name__)

ADVANCE_NEXT = {"QUEUED": "GLASS_CUT", "GLASS_CUT": "SEALED", "SEALED": "GAS_FILLED"}


# ------------------------------------------------------------------ waves

@bp_production.post("/fenestration/production-waves")
@require_roles("ProductionLead", "PlantManager")
def create_wave():
    body = body_json()
    w = new_entity({
        "wave_date": v_dt(need(body, "wave_date"), "wave_date"),
        "capacity_units": v_int(need(body, "capacity_units"), "capacity_units"),
        "capacity_glass_sqft": v_num(need(body, "capacity_glass_sqft"), "capacity_glass_sqft"),
        "allocated_units": 0, "allocated_glass_sqft": D(0), "status": "PLANNED",
    })
    STORE.waves[w["id"]] = w
    return obj_response(ser_wave(w), 201)


@bp_production.get("/fenestration/production-waves/<waveId>")
@require_roles(*ANY_ROLE)
def get_wave(waveId):
    return obj_response(ser_wave(get_or_404(STORE.waves, waveId)), 200)


@bp_production.post("/fenestration/production-waves/<waveId>/open")
@require_roles("ProductionLead", "PlantManager")
def open_wave(waveId):
    w = get_or_404(STORE.waves, waveId)
    if w["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a PLANNED wave can be opened")
    w["status"] = "OPEN"
    touch(w)
    return obj_response(ser_wave(w), 200)


@bp_production.post("/fenestration/production-waves/<waveId>/assignments")
@require_roles("ProductionLead", "PlantManager")
def assign_wave(waveId):
    w = get_or_404(STORE.waves, waveId)
    body = body_json()
    order_id = v_str(need(body, "order_id"), "order_id")
    order = get_or_404(STORE.orders, order_id)
    expected = v_int(need(body, "expected_wave_version"), "expected_wave_version")
    # OCC before any state/capacity examination of the wave.
    if expected != w["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_wave_version does not match current wave version")
    if w["status"] != "OPEN":
        raise ApiError("ERR_WAVE_NOT_OPEN", 409, "Wave is not OPEN")
    if order["production_status"] != "CONFIRMED":
        raise ApiError("ERR_ORDER_NOT_CONFIRMED", 409, "Order is not CONFIRMED")
    lines = live_lines(order["id"])
    max_lead = max(l["lead_time_days"] for l in lines)
    from datetime import timedelta
    if w["wave_date"] < order["order_date"] + timedelta(days=max_lead):
        raise ApiError("ERR_WAVE_BEFORE_LEAD_TIME", 409,
                       "wave_date is earlier than order_date + max line lead time")
    units, glass = wave_allocation(w, extra_lines=lines)
    if units > w["capacity_units"]:
        raise ApiError("ERR_WAVE_CAPACITY_EXCEEDED", 409,
                       "Assignment would exceed wave unit capacity")
    if glass > D(w["capacity_glass_sqft"]):
        raise ApiError("ERR_WAVE_GLASS_CAPACITY_EXCEEDED", 409,
                       "Assignment would exceed wave glass capacity")
    # Commit: order RELEASED, lines RELEASED, allocation recompute (bumps wave version).
    order["wave_id"] = w["id"]
    transition_order(order, "RELEASED")
    for line in lines:
        if line["status"] == "CONFIRMED":
            transition_line(line, "RELEASED")
    wave_recompute(w)
    return obj_response(ser_wave(w), 200)


@bp_production.post("/fenestration/production-waves/<waveId>/unassign")
@require_roles("ProductionLead", "PlantManager")
def unassign_wave(waveId):
    w = get_or_404(STORE.waves, waveId)
    body = body_json()
    order_id = v_str(need(body, "order_id"), "order_id")
    order = get_or_404(STORE.orders, order_id)
    if order["production_status"] != "RELEASED" or order["wave_id"] != w["id"]:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Order is not currently RELEASED on this wave")
    for line in lines_of_order(order["id"]):
        if line["status"] == "RELEASED":
            transition_line(line, "CONFIRMED")
    order["wave_id"] = None
    transition_order(order, "CONFIRMED")
    wave_recompute(w)
    return obj_response(ser_wave(w), 200)


@bp_production.post("/fenestration/production-waves/<waveId>/lock")
@require_roles("ProductionLead", "PlantManager")
def lock_wave(waveId):
    w = get_or_404(STORE.waves, waveId)
    if w["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an OPEN wave can be locked")
    w["status"] = "LOCKED"
    touch(w)
    return obj_response(ser_wave(w), 200)


@bp_production.post("/fenestration/production-waves/<waveId>/release")
@require_roles("ProductionLead", "PlantManager")
def release_wave(waveId):
    w = get_or_404(STORE.waves, waveId)
    if w["status"] != "LOCKED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a LOCKED wave can be released")
    assigned = [o for o in STORE.orders.values()
                if o["wave_id"] == w["id"] and o["production_status"] != "CANCELLED"]
    if not assigned:
        raise ApiError("ERR_INVALID_STATE", 409, "Wave has no assigned orders")
    w["status"] = "RELEASED"
    touch(w)
    for order in sorted(assigned, key=lambda o: o["_seq"]):
        if order["production_status"] != "RELEASED":
            continue  # orders already IN_PROGRESS are untouched
        transition_order(order, "IN_PROGRESS")
        for line in sorted(lines_of_order(order["id"]), key=lambda l: l["_seq"]):
            if line["status"] != "RELEASED":
                continue  # GLASS_HOLD / already-in-production lines untouched
            transition_line(line, "IN_PRODUCTION")
            gp = STORE.glass_packages[line["glass_package_id"]]
            for idx in range(1, line["quantity"] + 1):
                unit = new_entity({
                    "order_line_id": line["id"], "unit_index": idx,
                    "remake_of_id": None, "spacer_type": gp["spacer_type"],
                    "argon_measured_pct": None, "break_cause": None, "status": "QUEUED",
                })
                STORE.ig_units[unit["id"]] = unit
    return obj_response(ser_wave(w), 200)


@bp_production.post("/fenestration/production-waves/<waveId>/close")
@require_roles("ProductionLead", "PlantManager")
def close_wave(waveId):
    w = get_or_404(STORE.waves, waveId)
    if w["status"] != "RELEASED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a RELEASED wave can be closed")
    assigned = [o for o in STORE.orders.values() if o["wave_id"] == w["id"]]
    for o in assigned:
        if o["production_status"] in ("RELEASED", "IN_PROGRESS"):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Wave still has orders in flight")
        for line in lines_of_order(o["id"]):
            if line["status"] == "GLASS_HOLD":
                raise ApiError("ERR_INVALID_STATE", 409,
                               "Wave still has a line on GLASS_HOLD")
    w["status"] = "CLOSED"
    touch(w)
    return obj_response(ser_wave(w), 200)


@bp_production.post("/fenestration/production-waves/<waveId>/cancel")
@require_roles("ProductionLead", "PlantManager")
def cancel_wave(waveId):
    w = get_or_404(STORE.waves, waveId)
    if w["status"] not in ("PLANNED", "OPEN"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a PLANNED or OPEN wave can be cancelled")
    if w["allocated_units"] != 0:
        raise ApiError("ERR_WAVE_HAS_ASSIGNMENTS", 409,
                       "Wave has allocated units")
    w["status"] = "CANCELLED"
    touch(w)
    return obj_response(ser_wave(w), 200)


# ------------------------------------------------------------------ IG units

@bp_production.get("/fenestration/order-lines/<lineId>/ig-units")
@require_roles(*ANY_ROLE)
def list_line_ig_units(lineId):
    from common import check_ownership
    line = get_or_404(STORE.lines, lineId)
    order = STORE.orders.get(line["order_id"])
    if order:
        check_ownership(order["dealer_id"])
    units = [u for u in STORE.ig_units.values() if u["order_line_id"] == lineId]
    page, limit, offset, total = paginate(units)
    return list_response([ser_ig(u) for u in page], limit, offset, total)


@bp_production.get("/fenestration/ig-units/<igUnitId>")
@require_roles(*ANY_ROLE)
def get_ig_unit(igUnitId):
    return obj_response(ser_ig(get_or_404(STORE.ig_units, igUnitId)), 200)


@bp_production.get("/fenestration/ig-units")
@require_roles(*ANY_ROLE)
def list_ig_units():
    items = list(STORE.ig_units.values())
    for param in ("order_line_id", "remake_of_id"):
        val = request.args.get(param)
        if val is not None:
            items = [u for u in items if str(u.get(param)) == val]
    page, limit, offset, total = paginate(items)
    return list_response([ser_ig(u) for u in page], limit, offset, total)


@bp_production.post("/fenestration/ig-units/<igUnitId>/advance")
@require_roles("ProductionLead", "PlantManager")
def advance_ig_unit(igUnitId):
    unit = get_or_404(STORE.ig_units, igUnitId)
    if unit["status"] not in ADVANCE_NEXT:
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Unit in {unit['status']} cannot advance")
    line = STORE.lines.get(unit["order_line_id"])
    if line is None or line["status"] != "IN_PRODUCTION":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Parent order line is not IN_PRODUCTION")
    unit["status"] = ADVANCE_NEXT[unit["status"]]
    touch(unit)
    return obj_response(ser_ig(unit), 200)


@bp_production.post("/fenestration/ig-units/<igUnitId>/qc-check")
@require_roles("ProductionLead", "PlantManager")
def qc_check_ig_unit(igUnitId):
    unit = get_or_404(STORE.ig_units, igUnitId)
    body = body_json()
    measured = v_int(need(body, "argon_measured_pct"), "argon_measured_pct")
    if unit["status"] != "GAS_FILLED":
        raise ApiError("ERR_IG_NOT_READY_FOR_QC", 409, "Unit is not GAS_FILLED")
    line = STORE.lines.get(unit["order_line_id"])
    gp = STORE.glass_packages.get(line["glass_package_id"]) if line else None
    # Fill gate: inclusive boundary.
    pass_fill = measured >= gp["argon_min_pct"]
    # Code gate: applies only when the line's label has an applied rule.
    pass_code = True
    label = label_of_line(line["id"]) if line else None
    if label and label["applied_energy_code_rule_id"]:
        rule = STORE.energy_rules.get(label["applied_energy_code_rule_id"])
        if rule is not None:
            u_c = certified_u_factor(gp["catalog_u_factor"], gp["argon_target_pct"],
                                     measured, unit["spacer_type"])
            pass_code = (u_c <= D(rule["max_u_factor"])
                         and D(gp["catalog_shgc"]) <= D(rule["max_shgc"]))
    if pass_fill and pass_code:
        unit["argon_measured_pct"] = measured
        unit["status"] = "QC_PASSED"
        touch(unit)
        if line:
            line_completion_check(line)
        return obj_response(ser_ig(unit), 200)
    # Failure path: BROKEN (GAS_NONCOMPLIANCE) + auto-remake cascade (atomic).
    break_unit(unit, "GAS_NONCOMPLIANCE", measured=measured)
    return obj_response(ser_ig(unit), 200)


@bp_production.post("/fenestration/ig-units/<igUnitId>/report-breakage")
@require_roles("ProductionLead", "PlantManager")
def report_breakage(igUnitId):
    unit = get_or_404(STORE.ig_units, igUnitId)
    body = body_json()
    cause = v_enum(need(body, "break_cause"), "break_cause", MANUAL_BREAK_CAUSES)
    if unit["status"] not in ("QUEUED", "GLASS_CUT", "SEALED", "GAS_FILLED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Unit in {unit['status']} cannot be reported broken")
    break_unit(unit, cause)
    return obj_response(ser_ig(unit), 200)
