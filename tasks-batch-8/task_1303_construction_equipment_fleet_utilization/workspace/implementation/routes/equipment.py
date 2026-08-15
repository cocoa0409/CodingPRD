from flask import Blueprint, request

from db import fmt_ts, new_common, now, pub, pub_equipment, store, touch
from errors import ApiError, invalid_request, not_found
from logic import (IDLE_WINDOW_DAYS, OPEN_DAMAGE, OPEN_TRANSPORT,
                   OPEN_WORK_ORDER, fuel_summary, idle_streak_days,
                   recompute_active_count, redeployment_score, residual_value,
                   update_idle_marker)
from middleware import require_roles
from response import ok, ok_list
from util import (as_date, as_int, as_str, body_json, check_body_fks, paginate,
                  req_field)

bp = Blueprint("equipment", __name__)
READERS = ("FleetAdmin", "ProjectManager", "Mechanic", "Dispatcher")


def get_equipment_or_404(eid):
    e = store.equipment.get(eid)
    if e is None:
        raise not_found("Equipment")
    return e


@bp.post("/fleet/equipment")
@require_roles("FleetAdmin")
def create_equipment():
    body = body_json()
    # priority 4: body FK existence
    check_body_fks([(store.classes, body, "class_id")])
    # priority 5: well-formedness
    unit_tag = as_str(req_field(body, "unit_tag"), "unit_tag")
    class_id = as_str(req_field(body, "class_id"), "class_id")
    ownership = req_field(body, "ownership")
    if ownership not in ("OWNED", "RENTED"):
        raise invalid_request("ownership must be OWNED or RENTED")
    cost = req_field(body, "acquisition_cost_cents")
    if isinstance(cost, bool) or not isinstance(cost, int):
        raise invalid_request("acquisition_cost_cents must be an integer")
    acq_d, acq_raw = as_date(req_field(body, "acquisition_date"), "acquisition_date")
    months = req_field(body, "useful_life_months")
    if isinstance(months, bool) or not isinstance(months, int):
        raise invalid_request("useful_life_months must be an integer")
    # priority 6: ownership-typed field constraints
    if ownership == "OWNED":
        if cost <= 0 or months <= 0:
            raise ApiError("ERR_OWNERSHIP_FIELD_MISMATCH", 422,
                           "OWNED units require acquisition_cost_cents > 0 and useful_life_months > 0")
    else:
        if cost != 0:
            raise ApiError("ERR_OWNERSHIP_FIELD_MISMATCH", 422,
                           "RENTED units require acquisition_cost_cents == 0")
    if any(e["unit_tag"] == unit_tag for e in store.equipment.values()):
        raise invalid_request("unit_tag must be unique")
    e = new_common()
    e.update({
        "unit_tag": unit_tag,
        "class_id": class_id,
        "ownership": ownership,
        "acquisition_cost_cents": cost,
        "acquisition_date": acq_raw,
        "useful_life_months": months,
        "availability_status": "IDLE",
        "maintenance_status": "SERVICE_OK",
        "engine_hours_milli": 0,
        "hours_at_last_service_milli": 0,
        "current_project_id": None,
        "current_site_id": None,
        "disposed_at": None,
        "residual_value_cents": None,
        "_idle_ok_since": now(),
    })
    store.equipment[e["id"]] = e
    return ok(pub_equipment(e), "object", 201)


@bp.get("/fleet/equipment/<eid>")
@require_roles(*READERS)
def get_equipment(eid):
    return ok(pub_equipment(get_equipment_or_404(eid)), "object", 200)


@bp.get("/fleet/equipment")
@require_roles(*READERS)
def list_equipment():
    rows = list(store.equipment.values())
    for f in ("class_id", "availability_status", "current_site_id", "current_project_id"):
        v = request.args.get(f)
        if v is not None:
            rows = [e for e in rows if e.get(f) == v]
    items, meta = paginate(rows)
    return ok_list([pub_equipment(e) for e in items], meta)


@bp.post("/fleet/equipment/<eid>/mark-down")
@require_roles("FleetAdmin")
def mark_down(eid):
    e = get_equipment_or_404(eid)
    if e["availability_status"] not in ("IDLE", "ON_RENT"):
        raise ApiError("ERR_EQUIPMENT_NOT_AVAILABLE", 409,
                       "mark-down requires availability_status IDLE or ON_RENT")
    now_dt = now()
    if e["availability_status"] == "ON_RENT":
        for a in store.assignments.values():
            if a["equipment_id"] == e["id"] and a["status"] == "ACTIVE":
                a["status"] = "SUSPENDED"
                a["_suspensions"].append({"start": now_dt, "end": None})
                touch(a)
                proj = store.projects[a["project_id"]]
                if recompute_active_count(proj):
                    touch(proj)
    e["availability_status"] = "DOWN"
    update_idle_marker(e)
    touch(e)
    return ok(pub_equipment(e), "object", 200)


@bp.post("/fleet/equipment/<eid>/dispose")
@require_roles("FleetAdmin")
def dispose(eid):
    e = get_equipment_or_404(eid)
    body = body_json()
    method = req_field(body, "disposal_method")
    if method not in ("SALE", "SCRAP"):
        raise invalid_request("disposal_method must be SALE or SCRAP")
    if e["availability_status"] != "IDLE":
        raise ApiError("ERR_EQUIPMENT_NOT_AVAILABLE", 409,
                       "dispose requires availability_status IDLE")
    if e["ownership"] != "OWNED":
        raise ApiError("ERR_RENTED_UNIT", 422, "dispose requires ownership OWNED")
    open_work = (
        any(w for w in store.work_orders.values()
            if w["equipment_id"] == e["id"] and w["status"] in OPEN_WORK_ORDER)
        or any(t for t in store.transport_jobs.values()
               if t["equipment_id"] == e["id"] and t["status"] in OPEN_TRANSPORT)
        or any(d for d in store.damage_reports.values()
               if d["equipment_id"] == e["id"] and d["status"] in OPEN_DAMAGE)
    )
    if open_work:
        raise ApiError("ERR_OPEN_WORK", 409,
                       "dispose blocked by open work order, transport job, or damage report")
    cls = store.classes[e["class_id"]]
    now_dt = now()
    e["residual_value_cents"] = residual_value(e, cls, method, now_dt)
    e["disposed_at"] = fmt_ts(now_dt)
    e["availability_status"] = "DISPOSED"
    update_idle_marker(e)
    touch(e)
    return ok(pub_equipment(e), "object", 200)


@bp.get("/fleet/equipment/<eid>/redeployment-score")
@require_roles("FleetAdmin", "ProjectManager")
def redeployment(eid):
    e = get_equipment_or_404(eid)
    if e["availability_status"] != "IDLE":
        raise ApiError("ERR_EQUIPMENT_NOT_AVAILABLE", 409,
                       "redeployment-score requires an IDLE unit")
    cls = store.classes[e["class_id"]]
    candidates, recommended = redeployment_score(e, cls)
    streak = idle_streak_days(e)
    return ok({
        "idle_alert": streak >= IDLE_WINDOW_DAYS,
        "idle_streak_days": streak,
        "recommended_project_id": recommended,
        "candidates": candidates,
    }, "object", 200)


@bp.get("/fleet/equipment/<eid>/fuel-summary")
@require_roles("FleetAdmin", "ProjectManager")
def fuel(eid):
    e = get_equipment_or_404(eid)
    raw_from = request.args.get("from_date")
    raw_to = request.args.get("to_date")
    if raw_from is None or raw_to is None:
        raise invalid_request("from_date and to_date query parameters are required")
    _fd, from_raw = as_date(raw_from, "from_date")
    _td, to_raw = as_date(raw_to, "to_date")
    return ok(fuel_summary(e["id"], from_raw, to_raw), "object", 200)


# --- sub-resource reverse reachability listings ---

@bp.get("/fleet/equipment/<eid>/readings")
@require_roles(*READERS)
def equipment_readings(eid):
    e = get_equipment_or_404(eid)
    rows = [r for r in store.readings.values() if r["equipment_id"] == e["id"]]
    items, meta = paginate(rows)
    return ok_list([pub(r) for r in items], meta)


@bp.get("/fleet/equipment/<eid>/assignments")
@require_roles(*READERS)
def equipment_assignments(eid):
    e = get_equipment_or_404(eid)
    rows = [a for a in store.assignments.values() if a["equipment_id"] == e["id"]]
    st = request.args.get("status")
    if st is not None:
        rows = [a for a in rows if a["status"] == st]
    items, meta = paginate(rows)
    return ok_list([pub(a) for a in items], meta)


@bp.get("/fleet/equipment/<eid>/work-orders")
@require_roles(*READERS)
def equipment_work_orders(eid):
    e = get_equipment_or_404(eid)
    rows = [w for w in store.work_orders.values() if w["equipment_id"] == e["id"]]
    st = request.args.get("status")
    if st is not None:
        rows = [w for w in rows if w["status"] == st]
    items, meta = paginate(rows)
    return ok_list([pub(w) for w in items], meta)


@bp.get("/fleet/equipment/<eid>/damage-reports")
@require_roles(*READERS)
def equipment_damage_reports(eid):
    e = get_equipment_or_404(eid)
    rows = [d for d in store.damage_reports.values() if d["equipment_id"] == e["id"]]
    st = request.args.get("status")
    if st is not None:
        rows = [d for d in rows if d["status"] == st]
    items, meta = paginate(rows)
    return ok_list([pub(d) for d in items], meta)


@bp.get("/fleet/equipment/<eid>/transport-jobs")
@require_roles(*READERS)
def equipment_transport_jobs(eid):
    e = get_equipment_or_404(eid)
    rows = [t for t in store.transport_jobs.values() if t["equipment_id"] == e["id"]]
    st = request.args.get("status")
    if st is not None:
        rows = [t for t in rows if t["status"] == st]
    items, meta = paginate(rows)
    return ok_list([pub(t) for t in items], meta)
