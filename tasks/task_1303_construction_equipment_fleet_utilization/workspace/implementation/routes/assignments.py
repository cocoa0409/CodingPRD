from flask import Blueprint, request

from db import fmt_ts, new_common, new_sub, now, pub, store, touch
from errors import ApiError, invalid_request, invalid_state, not_found
from logic import (NON_TERMINAL_ASSIGNMENT, OPEN_TRANSPORT, compute_close,
                   hours_since_service, recompute_active_count,
                   update_idle_marker)
from middleware import require_roles
from response import ok, ok_list
from util import (as_date, as_int, as_str, body_json, check_body_fks, paginate,
                  req_field)

bp = Blueprint("assignments", __name__)
READERS = ("FleetAdmin", "ProjectManager", "Mechanic", "Dispatcher")
CLOSE_REASONS = ("COMPLETED", "EARLY_RETURN", "EQUIPMENT_DOWN", "PROJECT_CLOSED", "REDEPLOYED")


def get_assignment_or_404(aid):
    a = store.assignments.get(aid)
    if a is None:
        raise not_found("Assignment")
    return a


@bp.post("/fleet/assignments")
@require_roles("FleetAdmin")
def create_assignment():
    body = body_json()
    # priority 4: body FK existence
    check_body_fks([(store.equipment, body, "equipment_id"),
                    (store.projects, body, "project_id")])
    # priority 5: well-formedness
    equipment_id = as_str(req_field(body, "equipment_id"), "equipment_id")
    project_id = as_str(req_field(body, "project_id"), "project_id")
    start_d, start_raw = as_date(req_field(body, "start_date"), "start_date")
    end_d, end_raw = as_date(req_field(body, "end_date"), "end_date")
    if end_d <= start_d:
        raise invalid_request("end_date must be strictly after start_date")
    expected = req_field(body, "expected_equipment_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise invalid_request("expected_equipment_version must be an integer")
    e = store.equipment[equipment_id]
    # priority 8: availability gate
    if e["availability_status"] != "IDLE":
        raise ApiError("ERR_EQUIPMENT_NOT_AVAILABLE", 409,
                       "assignment create requires availability_status IDLE")
    # priority 9: maintenance gate
    if e["maintenance_status"] != "SERVICE_OK":
        raise ApiError("ERR_SERVICE_DUE", 409,
                       "assignment create requires maintenance_status SERVICE_OK")
    # priority 10: half-open window overlap vs non-terminal assignments
    for other in store.assignments.values():
        if other["equipment_id"] != e["id"] or other["status"] not in NON_TERMINAL_ASSIGNMENT:
            continue
        o_start = other["start_date"]
        o_end = other["end_date"]
        if start_raw < o_end and o_start < end_raw:
            raise ApiError("ERR_ASSIGNMENT_OVERLAP", 409,
                           "Assignment window overlaps a non-terminal assignment on this equipment")
    # priority 20: OCC
    if expected != e["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_equipment_version does not match the equipment version")
    a = new_common()
    a.update({
        "equipment_id": e["id"],
        "project_id": project_id,
        "start_date": start_raw,
        "end_date": end_raw,
        "status": "RESERVED",
        "activated_at": None,
        "closed_at": None,
        "billable_days": 0,
        "idle_days": 0,
        "engine_hours_billed_milli": 0,
        "utilization_elapsed_bp": None,
        "utilization_billing_bp": None,
        "close_reason": None,
        "_activated_dt": None,
        "_closed_dt": None,
        "_suspensions": [],
    })
    store.assignments[a["id"]] = a
    e["availability_status"] = "RESERVED"
    update_idle_marker(e)
    touch(e)
    return ok(pub(a), "object", 201)


@bp.get("/fleet/assignments/<aid>")
@require_roles(*READERS)
def get_assignment(aid):
    return ok(pub(get_assignment_or_404(aid)), "object", 200)


@bp.get("/fleet/assignments")
@require_roles(*READERS)
def list_assignments():
    rows = list(store.assignments.values())
    for f in ("equipment_id", "project_id", "status"):
        v = request.args.get(f)
        if v is not None:
            rows = [a for a in rows if a.get(f) == v]
    items, meta = paginate(rows)
    return ok_list([pub(a) for a in items], meta)


@bp.post("/fleet/assignments/<aid>/activate")
@require_roles("FleetAdmin")
def activate_assignment(aid):
    a = get_assignment_or_404(aid)
    if a["status"] != "RESERVED":
        raise invalid_state("Only a RESERVED assignment can be activated")
    e = store.equipment[a["equipment_id"]]
    if e["availability_status"] != "RESERVED":
        raise ApiError("ERR_EQUIPMENT_NOT_AVAILABLE", 409,
                       "activate requires equipment availability_status RESERVED")
    if e["maintenance_status"] != "SERVICE_OK":
        raise ApiError("ERR_SERVICE_DUE", 409,
                       "activate requires maintenance_status SERVICE_OK")
    cls = store.classes[e["class_id"]]
    p = store.projects[a["project_id"]]
    # budget guard (inclusive cap), checked before the project-open gate
    if p["billed_total_cents"] + cls["daily_rate_cents"] > p["equipment_budget_cents"]:
        raise ApiError("ERR_BUDGET_EXCEEDED", 422,
                       "Projected first-day charge would exceed the project equipment budget")
    if p["status"] != "OPEN":
        raise ApiError("ERR_PROJECT_NOT_OPEN", 409, "Project must be OPEN for activation")
    now_dt = now()
    a["status"] = "ACTIVE"
    a["activated_at"] = fmt_ts(now_dt)
    a["_activated_dt"] = now_dt
    touch(a)
    e["availability_status"] = "ON_RENT"
    e["current_project_id"] = a["project_id"]
    e["current_site_id"] = a["project_id"]
    update_idle_marker(e)
    touch(e)
    if recompute_active_count(p):
        touch(p)
    return ok(pub(a), "object", 200)


@bp.post("/fleet/assignments/<aid>/close")
@require_roles("FleetAdmin")
def close_assignment(aid):
    a = get_assignment_or_404(aid)
    body = body_json()
    reason = req_field(body, "close_reason")
    if reason not in CLOSE_REASONS:
        raise invalid_request("close_reason must be one of " + ", ".join(CLOSE_REASONS))
    if a["status"] not in ("ACTIVE", "SUSPENDED"):
        raise invalid_state("Only an ACTIVE or SUSPENDED assignment can be closed")
    if a["status"] == "SUSPENDED" and reason not in ("EQUIPMENT_DOWN", "PROJECT_CLOSED"):
        raise invalid_request(
            "close_reason must be EQUIPMENT_DOWN or PROJECT_CLOSED when closing from SUSPENDED")
    if any(t for t in store.transport_jobs.values()
           if t.get("assignment_id") == a["id"] and t["status"] in OPEN_TRANSPORT):
        raise ApiError("ERR_TRANSPORT_PENDING", 409,
                       "Assignment close is blocked by a PLANNED or EN_ROUTE transport job")
    e = store.equipment[a["equipment_id"]]
    cls = store.classes[e["class_id"]]
    p = store.projects[a["project_id"]]
    now_dt = now()
    res = compute_close(a, e, cls, now_dt)
    was_active = a["status"] == "ACTIVE"
    a["status"] = "CLOSED"
    a["closed_at"] = fmt_ts(now_dt)
    a["_closed_dt"] = now_dt
    a["close_reason"] = reason
    a["billable_days"] = res["billable_days"]
    a["idle_days"] = res["idle_days"]
    a["engine_hours_billed_milli"] = res["milli"]
    a["utilization_elapsed_bp"] = res["util_elapsed"]
    a["utilization_billing_bp"] = res["util_billing"]
    touch(a)
    charge = new_sub()
    charge.update({
        "assignment_id": a["id"],
        "project_id": p["id"],
        "allocated_cents": res["allocated"],
        "own_cost_cents": res["own"],
        "rent_cost_cents": res["rent"],
        "cheaper_variant": res["cheaper"],
    })
    store.charges[charge["id"]] = charge
    changed = False
    if res["allocated"] != 0:
        p["billed_total_cents"] += res["allocated"]
        changed = True
    if recompute_active_count(p):
        changed = True
    if changed:
        touch(p)
    e["current_project_id"] = None
    if was_active:
        e["availability_status"] = "IDLE"
    update_idle_marker(e)
    touch(e)
    return ok(pub(a), "object", 200)


@bp.post("/fleet/assignments/<aid>/cancel")
@require_roles("FleetAdmin")
def cancel_assignment(aid):
    a = get_assignment_or_404(aid)
    if a["status"] != "RESERVED":
        raise invalid_state("Only a RESERVED assignment can be cancelled")
    a["status"] = "CANCELLED"
    touch(a)
    e = store.equipment[a["equipment_id"]]
    e["availability_status"] = "IDLE"
    update_idle_marker(e)
    touch(e)
    return ok(pub(a), "object", 200)


@bp.get("/fleet/assignments/<aid>/charges")
@require_roles("FleetAdmin", "ProjectManager")
def assignment_charges(aid):
    a = get_assignment_or_404(aid)
    rows = [c for c in store.charges.values() if c["assignment_id"] == a["id"]]
    items, meta = paginate(rows)
    return ok_list([pub(c) for c in items], meta)
