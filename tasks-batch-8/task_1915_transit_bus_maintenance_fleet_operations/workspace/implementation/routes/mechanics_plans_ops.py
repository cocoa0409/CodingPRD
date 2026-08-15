"""Mechanic, certification, replacement plan, clock/epoch/posture routes."""
from flask import Blueprint, request

from errors import err
from httpkit import (require_roles, body, req_str, req_int, req_enum, req_date,
                     parse_iso_datetime, paginate, sort_default, success)
from store import db, init_common, mark_dirty, set_clock, clock_date, fmt_ts, \
    clock_now
from services import domain as dom
from services import cascades
from services import serializers as ser
from routes.buses import ALL

bp = Blueprint("mechanics_plans_ops", __name__)


# ---------------------------------------------------------------------------
# Clock & epoch & posture
# ---------------------------------------------------------------------------
@bp.post("/fleet/_clock/set_current_utc")
def set_clock_route():
    require_roles("FleetManager")
    data = body()
    val = data.get("to_iso8601")
    if val is None:
        raise err("ERR_VALIDATION", "Missing required field: to_iso8601")
    dt = parse_iso_datetime(val)
    set_clock(dt)
    return success({"current_utc": fmt_ts(clock_now())})


@bp.post("/fleet/run_epoch")
def run_epoch_route():
    require_roles("FleetManager")
    result = cascades.run_epoch()
    return success(result)


@bp.get("/fleet/posture")
def get_posture():
    require_roles(*ALL)
    return success(dom.current_posture())


# ---------------------------------------------------------------------------
# Mechanics & certifications
# ---------------------------------------------------------------------------
def get_mechanic_or_404(mechanic_id):
    m = db["mechanics"].get(mechanic_id)
    if m is None:
        raise err("ERR_NOT_FOUND", f"Mechanic {mechanic_id} not found")
    return m


@bp.post("/fleet/mechanics")
def create_mechanic():
    require_roles("MaintenanceSupervisor")
    data = body()
    name = req_str(data, "name")
    employee_ref = req_str(data, "employee_ref")
    mech = init_common({
        "name": name,
        "employee_ref": employee_ref,
        "employment_status": "ACTIVE",
    })
    db["mechanics"][mech["id"]] = mech
    return success(ser.mechanic(mech), code=201)


@bp.get("/fleet/mechanics/<mid>")
def get_mechanic(mid):
    require_roles(*ALL)
    return success(ser.mechanic(get_mechanic_or_404(mid)))


@bp.get("/fleet/mechanics")
def list_mechanics():
    require_roles(*ALL)
    items = sort_default(list(db["mechanics"].values()))
    page, meta_p = paginate(items)
    return success([ser.mechanic(m) for m in page], response_type="array",
                   pagination=meta_p)


@bp.get("/fleet/mechanics/<mid>/shift-assignments")
def mechanic_assignments(mid):
    require_roles(*ALL)
    get_mechanic_or_404(mid)
    items = sort_default([a for a in db["assignments"].values()
                          if a["mechanic_id"] == mid])
    page, meta_p = paginate(items)
    return success([ser.assignment(a) for a in page], response_type="array",
                   pagination=meta_p)


@bp.get("/fleet/mechanics/<mid>/work-orders")
def mechanic_wos(mid):
    require_roles(*ALL)
    get_mechanic_or_404(mid)
    items = sort_default([w for w in db["work_orders"].values()
                          if w.get("lead_mechanic_id") == mid])
    page, meta_p = paginate(items)
    return success([ser.work_order(w) for w in page], response_type="array",
                   pagination=meta_p)


@bp.get("/fleet/mechanics/<mid>/defect-reports")
def mechanic_defects(mid):
    require_roles(*ALL)
    get_mechanic_or_404(mid)
    items = sort_default([d for d in db["defects"].values()
                          if d.get("road_call_mechanic_id") == mid])
    page, meta_p = paginate(items)
    return success([ser.defect(d) for d in page], response_type="array",
                   pagination=meta_p)


@bp.post("/fleet/mechanics/<mid>/certifications")
def create_certification(mid):
    require_roles("MaintenanceSupervisor")
    get_mechanic_or_404(mid)
    data = body()
    cert_type = req_enum(data, "cert_type", dom.CERT_TYPES)
    issued = req_date(data, "issued_date")
    expiry = req_date(data, "expiry_date")
    if issued > expiry:
        raise err("ERR_VALIDATION",
                  "issued_date must be on or before expiry_date")
    cert = init_common({
        "mechanic_id": mid,
        "cert_type": cert_type,
        "issued_date": issued.isoformat(),
        "expiry_date": expiry.isoformat(),
        "status": "VALID",
    })
    db["certifications"][cert["id"]] = cert
    return success(ser.certification(cert), code=201)


@bp.get("/fleet/mechanics/<mid>/certifications")
def mechanic_certs(mid):
    require_roles(*ALL)
    get_mechanic_or_404(mid)
    items = sort_default([c for c in db["certifications"].values()
                          if c["mechanic_id"] == mid])
    page, meta_p = paginate(items)
    return success([ser.certification(c) for c in page], response_type="array",
                   pagination=meta_p)


@bp.get("/fleet/certifications/<cid>")
def get_certification(cid):
    require_roles(*ALL)
    cert = db["certifications"].get(cid)
    if cert is None:
        raise err("ERR_NOT_FOUND", f"MechanicCertification {cid} not found")
    return success(ser.certification(cert))


@bp.post("/fleet/certifications/<cid>/renew")
def renew_certification(cid):
    require_roles("MaintenanceSupervisor")
    cert = db["certifications"].get(cid)
    if cert is None:
        raise err("ERR_NOT_FOUND", f"MechanicCertification {cid} not found")
    data = body()
    new_expiry = req_date(data, "new_expiry_date")
    if new_expiry <= clock_date():
        raise err("ERR_VALIDATION",
                  "new_expiry_date must be after the logical clock date")
    cert["expiry_date"] = new_expiry.isoformat()
    cert["status"] = "VALID"
    mark_dirty("certifications", cert["id"])
    return success(ser.certification(cert))


# ---------------------------------------------------------------------------
# Fleet replacement plans
# ---------------------------------------------------------------------------
@bp.post("/fleet/replacement-plans")
def create_plan():
    require_roles("FleetManager")
    data = body()
    plan_year = req_int(data, "plan_year")
    for p in db["plans"].values():
        if p["status"] in ("DRAFT", "APPROVED", "EXECUTING"):
            raise err("ERR_PLAN_ALREADY_OPEN",
                      "Another fleet replacement plan is already open")
    scores = dom.compute_replacement_scores()
    plan = init_common({
        "plan_year": plan_year,
        "status": "DRAFT",
        "scores": scores,
    })
    db["plans"][plan["id"]] = plan
    return success(ser.plan(plan), code=201)


@bp.get("/fleet/replacement-plans/<pid>")
def get_plan(pid):
    require_roles(*ALL)
    plan = db["plans"].get(pid)
    if plan is None:
        raise err("ERR_NOT_FOUND", f"FleetReplacementPlan {pid} not found")
    return success(ser.plan(plan))


_PLAN_EVENTS = {"APPROVE", "EXECUTE", "CLOSE"}
_PLAN_FROM = {
    "APPROVE": {"DRAFT"},
    "EXECUTE": {"APPROVED"},
    "CLOSE": {"EXECUTING"},
}


@bp.post("/fleet/replacement-plans/<pid>/events")
def plan_event(pid):
    require_roles("FleetManager")
    plan = db["plans"].get(pid)
    if plan is None:
        raise err("ERR_NOT_FOUND", f"FleetReplacementPlan {pid} not found")
    data = body()
    event_type = req_enum(data, "event_type", _PLAN_EVENTS)
    if plan["status"] == "CLOSED":
        raise err("ERR_ALREADY_TERMINAL", "Plan is CLOSED")
    if plan["status"] not in _PLAN_FROM[event_type]:
        raise err("ERR_INVALID_STATE",
                  f"Cannot {event_type} a plan in {plan['status']}")
    plan["status"] = {"APPROVE": "APPROVED", "EXECUTE": "EXECUTING",
                      "CLOSE": "CLOSED"}[event_type]
    mark_dirty("plans", plan["id"])
    return success(ser.plan(plan))
