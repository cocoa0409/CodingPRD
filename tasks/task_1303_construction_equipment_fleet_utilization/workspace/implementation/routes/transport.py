from flask import Blueprint, request

from db import new_common, pub, store, touch
from errors import ApiError, invalid_request, invalid_state, not_found
from logic import lowboy_conflict, update_idle_marker
from middleware import require_roles
from response import ok, ok_list
from util import (as_datetime, as_str, body_json, check_body_fks, paginate,
                  req_field)

bp = Blueprint("transport", __name__)
READERS = ("FleetAdmin", "ProjectManager", "Mechanic", "Dispatcher")


def get_job_or_404(tid):
    t = store.transport_jobs.get(tid)
    if t is None:
        raise not_found("TransportJob")
    return t


@bp.post("/fleet/transport-jobs")
@require_roles("Dispatcher")
def create_transport_job():
    body = body_json()
    # priority 4: body FK existence
    check_body_fks([(store.equipment, body, "equipment_id"),
                    (store.projects, body, "from_project_id"),
                    (store.projects, body, "to_project_id"),
                    (store.lowboys, body, "lowboy_id"),
                    (store.assignments, body, "assignment_id")])
    # priority 5: well-formedness
    equipment_id = as_str(req_field(body, "equipment_id"), "equipment_id")
    from_id = as_str(req_field(body, "from_project_id"), "from_project_id")
    to_id = as_str(req_field(body, "to_project_id"), "to_project_id")
    lowboy_id = as_str(req_field(body, "lowboy_id"), "lowboy_id")
    if to_id == from_id:
        raise invalid_request("to_project_id must differ from from_project_id")
    dep_dt, dep_raw = as_datetime(req_field(body, "depart_at"), "depart_at")
    arr_dt, arr_raw = as_datetime(req_field(body, "arrive_at"), "arrive_at")
    if arr_dt <= dep_dt:
        raise invalid_request("arrive_at must be strictly after depart_at")
    assignment_id = body.get("assignment_id")
    if assignment_id is not None and not isinstance(assignment_id, str):
        raise invalid_request("assignment_id must be a string")
    # priority 8: equipment availability gate
    e = store.equipment[equipment_id]
    if e["availability_status"] != "IDLE":
        raise ApiError("ERR_EQUIPMENT_NOT_AVAILABLE", 409,
                       "transport create requires availability_status IDLE")
    # priority 11: origin-site agreement + buffered lowboy interval conflict
    if e["current_site_id"] != from_id:
        raise ApiError("ERR_TRANSPORT_CONFLICT", 409,
                       "Equipment is not physically at from_project_id")
    if lowboy_conflict(lowboy_id, dep_dt, arr_dt):
        raise ApiError("ERR_TRANSPORT_CONFLICT", 409,
                       "Buffered transport interval conflicts with another job on the lowboy")
    t = new_common()
    t.update({
        "equipment_id": equipment_id,
        "from_project_id": from_id,
        "to_project_id": to_id,
        "lowboy_id": lowboy_id,
        "depart_at": dep_raw,
        "arrive_at": arr_raw,
        "status": "PLANNED",
        "assignment_id": assignment_id,
        "_depart_dt": dep_dt,
        "_arrive_dt": arr_dt,
    })
    store.transport_jobs[t["id"]] = t
    e["availability_status"] = "IN_TRANSIT"
    update_idle_marker(e)
    touch(e)
    return ok(pub(t), "object", 201)


@bp.get("/fleet/transport-jobs/<tid>")
@require_roles(*READERS)
def get_transport_job(tid):
    return ok(pub(get_job_or_404(tid)), "object", 200)


@bp.get("/fleet/transport-jobs")
@require_roles(*READERS)
def list_transport_jobs():
    rows = list(store.transport_jobs.values())
    for f in ("equipment_id", "lowboy_id", "assignment_id", "status"):
        v = request.args.get(f)
        if v is not None:
            rows = [t for t in rows if t.get(f) == v]
    items, meta = paginate(rows)
    return ok_list([pub(t) for t in items], meta)


@bp.post("/fleet/transport-jobs/<tid>/depart")
@require_roles("Dispatcher")
def depart(tid):
    t = get_job_or_404(tid)
    if t["status"] != "PLANNED":
        raise invalid_state("Only a PLANNED transport job can depart")
    e = store.equipment[t["equipment_id"]]
    if e["availability_status"] != "IN_TRANSIT":
        raise invalid_state("Departure requires the equipment to be IN_TRANSIT")
    t["status"] = "EN_ROUTE"
    touch(t)
    lb = store.lowboys[t["lowboy_id"]]
    lb["status"] = "ON_Haul"
    touch(lb)
    return ok(pub(t), "object", 200)


@bp.post("/fleet/transport-jobs/<tid>/deliver")
@require_roles("Dispatcher")
def deliver(tid):
    t = get_job_or_404(tid)
    if t["status"] != "EN_ROUTE":
        raise invalid_state("Only an EN_ROUTE transport job can be delivered")
    t["status"] = "DELIVERED"
    touch(t)
    e = store.equipment[t["equipment_id"]]
    e["availability_status"] = "IDLE"
    e["current_site_id"] = t["to_project_id"]
    update_idle_marker(e)
    touch(e)
    lb = store.lowboys[t["lowboy_id"]]
    lb["status"] = "AVAILABLE"
    touch(lb)
    return ok(pub(t), "object", 200)


@bp.post("/fleet/transport-jobs/<tid>/cancel")
@require_roles("Dispatcher")
def cancel(tid):
    t = get_job_or_404(tid)
    if t["status"] != "PLANNED":
        raise invalid_state("Only a PLANNED transport job can be cancelled")
    t["status"] = "CANCELLED"
    touch(t)
    e = store.equipment[t["equipment_id"]]
    e["availability_status"] = "IDLE"
    update_idle_marker(e)
    touch(e)
    return ok(pub(t), "object", 200)
