from flask import Blueprint, g, request

from db import fmt_ts, new_common, now, pub, store, touch
from errors import ApiError, invalid_request, invalid_state, not_found
from logic import (hours_since_service, make_work_order, mechanic_recompute,
                   recompute_active_count, service_threshold_milli,
                   update_idle_marker)
from middleware import require_roles
from response import ok, ok_list
from util import as_str, body_json, check_body_fks, paginate, req_field

bp = Blueprint("workorders", __name__)
READERS = ("FleetAdmin", "ProjectManager", "Mechanic", "Dispatcher")


def get_wo_or_404(wid):
    w = store.work_orders.get(wid)
    if w is None:
        raise not_found("WorkOrder")
    return w


@bp.post("/fleet/work-orders")
@require_roles("FleetAdmin")
def create_work_order():
    body = body_json()
    check_body_fks([(store.equipment, body, "equipment_id")])
    equipment_id = as_str(req_field(body, "equipment_id"), "equipment_id")
    kind = req_field(body, "kind")
    if kind not in ("PREVENTIVE", "REPAIR"):
        raise invalid_request("kind must be PREVENTIVE or REPAIR")
    notes = body.get("notes", "")
    if notes is None:
        notes = ""
    if not isinstance(notes, str):
        raise invalid_request("notes must be a string")
    e = store.equipment[equipment_id]
    wo = make_work_order(e, kind, notes=notes, auto=False)
    return ok(pub(wo), "object", 201)


@bp.get("/fleet/work-orders/<wid>")
@require_roles(*READERS)
def get_work_order(wid):
    return ok(pub(get_wo_or_404(wid)), "object", 200)


@bp.get("/fleet/work-orders")
@require_roles(*READERS)
def list_work_orders():
    rows = list(store.work_orders.values())
    for f in ("equipment_id", "mechanic_id", "status"):
        v = request.args.get(f)
        if v is not None:
            rows = [w for w in rows if w.get(f) == v]
    items, meta = paginate(rows)
    return ok_list([pub(w) for w in items], meta)


@bp.post("/fleet/work-orders/<wid>/dispatch")
@require_roles("FleetAdmin")
def dispatch_work_order(wid):
    wo = get_wo_or_404(wid)
    body = body_json()
    check_body_fks([(store.mechanics, body, "mechanic_id")])
    mechanic_id = as_str(req_field(body, "mechanic_id"), "mechanic_id")
    if wo["status"] != "OPEN":
        raise invalid_state("Only an OPEN work order can be dispatched")
    m = store.mechanics[mechanic_id]
    if m["status"] != "AVAILABLE" or m["active_work_order_count"] >= 2:
        raise ApiError("ERR_MECHANIC_UNAVAILABLE", 409,
                       "Mechanic is not AVAILABLE or already carries 2 active work orders")
    wo["mechanic_id"] = m["id"]
    wo["dispatched_at"] = fmt_ts(now())
    wo["status"] = "DISPATCHED"
    touch(wo)
    m["active_work_order_count"] += 1
    mechanic_recompute(m)
    touch(m)
    return ok(pub(wo), "object", 200)


@bp.post("/fleet/work-orders/<wid>/start")
@require_roles("Mechanic")
def start_work_order(wid):
    wo = get_wo_or_404(wid)
    if wo["status"] != "DISPATCHED":
        raise invalid_state("Only a DISPATCHED work order can be started")
    if wo["mechanic_id"] != g.user_id:
        raise ApiError("ERR_NOT_ASSIGNED_MECHANIC", 403,
                       "The acting mechanic is not the work order's dispatched mechanic")
    wo["status"] = "IN_PROGRESS"
    touch(wo)
    e = store.equipment[wo["equipment_id"]]
    e["maintenance_status"] = "IN_SERVICE"
    update_idle_marker(e)
    touch(e)
    return ok(pub(wo), "object", 200)


@bp.post("/fleet/work-orders/<wid>/complete")
@require_roles("Mechanic")
def complete_work_order(wid):
    wo = get_wo_or_404(wid)
    if wo["status"] != "IN_PROGRESS":
        raise invalid_state("Only an IN_PROGRESS work order can be completed")
    if wo["mechanic_id"] != g.user_id:
        raise ApiError("ERR_NOT_ASSIGNED_MECHANIC", 403,
                       "The acting mechanic is not the work order's dispatched mechanic")
    now_dt = now()
    wo["status"] = "COMPLETED"
    wo["completed_at"] = fmt_ts(now_dt)
    touch(wo)
    e = store.equipment[wo["equipment_id"]]
    e["hours_at_last_service_milli"] = e["engine_hours_milli"]
    e["maintenance_status"] = "SERVICE_OK"
    if wo["kind"] == "REPAIR" and e["availability_status"] == "DOWN":
        e["availability_status"] = "IDLE"
        # Reactivation cascade: earliest-created SUSPENDED assignment whose
        # project is OPEN goes back ACTIVE and the unit returns ON_RENT for it.
        suspended = sorted(
            (a for a in store.assignments.values()
             if a["equipment_id"] == e["id"] and a["status"] == "SUSPENDED"),
            key=lambda a: (a["created_at"], a["_seq"]))
        for a in suspended:
            proj = store.projects[a["project_id"]]
            if proj["status"] == "OPEN":
                a["status"] = "ACTIVE"
                if a["_suspensions"] and a["_suspensions"][-1]["end"] is None:
                    a["_suspensions"][-1]["end"] = now_dt
                touch(a)
                e["availability_status"] = "ON_RENT"
                if recompute_active_count(proj):
                    touch(proj)
                break
    update_idle_marker(e)
    touch(e)
    m = store.mechanics.get(wo["mechanic_id"])
    if m is not None:
        m["active_work_order_count"] = max(0, m["active_work_order_count"] - 1)
        mechanic_recompute(m)
        touch(m)
    return ok(pub(wo), "object", 200)


@bp.post("/fleet/work-orders/<wid>/cancel")
@require_roles("FleetAdmin")
def cancel_work_order(wid):
    wo = get_wo_or_404(wid)
    if wo["status"] not in ("OPEN", "DISPATCHED"):
        raise invalid_state("Only an OPEN or DISPATCHED work order can be cancelled")
    if wo["status"] == "DISPATCHED":
        m = store.mechanics.get(wo["mechanic_id"])
        wo["mechanic_id"] = None
        if m is not None:
            m["active_work_order_count"] = max(0, m["active_work_order_count"] - 1)
            mechanic_recompute(m)
            touch(m)
        e = store.equipment[wo["equipment_id"]]
        cls = store.classes[e["class_id"]]
        new_status = ("SERVICE_DUE" if hours_since_service(e) >= service_threshold_milli(cls)
                      else "SERVICE_OK")
        if new_status != e["maintenance_status"]:
            e["maintenance_status"] = new_status
            update_idle_marker(e)
            touch(e)
    wo["status"] = "CANCELLED"
    touch(wo)
    return ok(pub(wo), "object", 200)
