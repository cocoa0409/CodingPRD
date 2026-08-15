"""RepairOrder and ExcavationPermit endpoints (PRD §3.6)."""
from flask import request

from db import STORE, make_entity, now, serialize, touch
from errors import bad_request, err
from middleware import (body, opt_body, parse_pagination, req_dt, req_str,
                        require_roles)
from response import list_response, success
from services import (EXCAVATION_METHODS, FIELDS, crew_dispatch_score,
                      get_or_404, has_valid_permit, recompute_crew_status,
                      sorted_all)
from . import bp

ORDER_ROLES = ("DispatchCoordinator", "IntegrityAnalyst", "ComplianceOfficer")


def ser_order(o):
    return serialize(o, FIELDS["repair_orders"])


def ser_permit(p):
    return serialize(p, FIELDS["excavation_permits"])


@bp.get("/repair-orders")
@require_roles(*ORDER_ROLES)
def list_orders():
    limit, offset = parse_pagination()
    ds = request.args.get("dispatch_status")
    eps = request.args.get("excavation_permit_status")
    crew_id = request.args.get("crew_id")
    leak_id = request.args.get("leak_id")
    items = sorted_all("repair_orders")
    if ds is not None:
        items = [o for o in items if o["dispatch_status"] == ds]
    if eps is not None:
        items = [o for o in items if o["excavation_permit_status"] == eps]
    if crew_id is not None:
        items = [o for o in items if o.get("crew_id") == crew_id]
    if leak_id is not None:
        items = [o for o in items if o["leak_id"] == leak_id]
    return list_response(items, ser_order, limit, offset)


@bp.get("/repair-orders/<oid>")
@require_roles(*ORDER_ROLES)
def get_order(oid):
    return success(ser_order(get_or_404("repair_orders", oid)))


def _needs_excavation(order):
    return order["repair_method"] in EXCAVATION_METHODS


def _check_permit(order):
    if not has_valid_permit(order):
        raise err("ERR_NO_VALID_EXCAVATION_PERMIT",
                  "No GRANTED ExcavationPermit with expires_at > current clock "
                  "for this order", 422)


def _check_crew(order, crew):
    if crew["status"] == "OFF_DUTY":
        raise err("ERR_CREW_OFF_DUTY", "RepairCrew.status == OFF_DUTY", 422)
    # PRD §2.5: business-temporal checks (permit validity) are evaluated
    # before business-constraint checks (crew capacity, crew qualification).
    if _needs_excavation(order):
        _check_permit(order)
    if crew["open_order_count"] >= crew["max_concurrent_orders"]:
        raise err("ERR_CREW_AT_CAPACITY",
                  "RepairCrew.open_order_count >= max_concurrent_orders", 422)
    if _needs_excavation(order) and not crew["is_qualified_excavation"]:
        raise err("ERR_CREW_NOT_QUALIFIED_EXCAVATION",
                  "RepairCrew.is_qualified_excavation == false but "
                  "repair_method requires excavation", 422)


def _select_crew(order, seg):
    candidates = []
    for crew in STORE["repair_crews"].values():
        if crew["status"] == "OFF_DUTY":
            continue
        if crew["open_order_count"] >= crew["max_concurrent_orders"]:
            continue
        if _needs_excavation(order) and not crew["is_qualified_excavation"]:
            continue
        candidates.append(crew)
    if not candidates:
        raise err("ERR_NO_ELIGIBLE_CREW",
                  "Crew selector policy returned empty candidate set", 422)
    scored = [(crew_dispatch_score(c, seg), c) for c in candidates]
    scored.sort(key=lambda t: (-t[0], t[1]["open_order_count"],
                               t[1]["created_at"], t[1]["_seq"]))
    return scored[0][1]


@bp.post("/repair-orders/<oid>/dispatch")
@require_roles("DispatchCoordinator")
def dispatch_order(oid):
    order = get_or_404("repair_orders", oid)
    d = opt_body()
    crew_id = d.get("crew_id")
    if crew_id is not None and not isinstance(crew_id, str):
        raise bad_request("crew_id must be a string")
    if order["dispatch_status"] != "PENDING_DISPATCH":
        raise err("ERR_ORDER_NOT_PENDING_DISPATCH",
                  "RepairOrder.dispatch_status != PENDING_DISPATCH", 409)
    leak = STORE["leaks"].get(order["leak_id"])
    seg = (STORE["pipe_segments"].get(leak["segment_id"])
           if leak is not None else None)
    if crew_id is not None:
        crew = get_or_404("repair_crews", crew_id)
        _check_crew(order, crew)
    else:
        if _needs_excavation(order):
            _check_permit(order)
        crew = _select_crew(order, seg if seg is not None else {})
    order["crew_id"] = crew["id"]
    order["dispatched_at"] = now()
    order["dispatch_status"] = "DISPATCHED"
    touch(order)
    crew["open_order_count"] += 1
    recompute_crew_status(crew)
    touch(crew)
    return success(ser_order(order))


@bp.post("/repair-orders/<oid>/arrive-on-site")
@require_roles("DispatchCoordinator")
def arrive_on_site(oid):
    order = get_or_404("repair_orders", oid)
    if order["dispatch_status"] != "DISPATCHED":
        raise err("ERR_ORDER_NOT_DISPATCHED",
                  "RepairOrder.dispatch_status != DISPATCHED", 409)
    order["dispatch_status"] = "ON_SITE"
    touch(order)
    leak = STORE["leaks"].get(order["leak_id"])
    if leak is not None and leak["status"] == "REPAIR_SCHEDULED":
        leak["status"] = "UNDER_REPAIR"
        touch(leak)
    return success(ser_order(order))


@bp.post("/repair-orders/<oid>/mark-work-complete")
@require_roles("DispatchCoordinator")
def mark_work_complete(oid):
    order = get_or_404("repair_orders", oid)
    if order["dispatch_status"] != "ON_SITE":
        raise err("ERR_ORDER_NOT_ON_SITE",
                  "RepairOrder.dispatch_status != ON_SITE", 409)
    order["dispatch_status"] = "WORK_COMPLETE"
    order["completed_at"] = now()
    touch(order)
    crew = (STORE["repair_crews"].get(order["crew_id"])
            if order.get("crew_id") else None)
    if crew is not None:
        crew["open_order_count"] = max(0, crew["open_order_count"] - 1)
        recompute_crew_status(crew)
        touch(crew)
    leak = STORE["leaks"].get(order["leak_id"])
    if leak is not None and leak["status"] == "UNDER_REPAIR":
        leak["status"] = "REPAIRED_PENDING_VERIFICATION"
        touch(leak)
    return success(ser_order(order))


@bp.post("/repair-orders/<oid>/cancel")
@require_roles("DispatchCoordinator")
def cancel_order(oid):
    order = get_or_404("repair_orders", oid)
    if order["dispatch_status"] not in ("PENDING_DISPATCH", "DISPATCHED"):
        raise err("ERR_ORDER_NOT_CANCELLABLE",
                  "RepairOrder.dispatch_status not in "
                  "{PENDING_DISPATCH, DISPATCHED}", 409)
    was_dispatched = order["dispatch_status"] == "DISPATCHED"
    order["dispatch_status"] = "CANCELLED"
    touch(order)
    if was_dispatched:
        crew = (STORE["repair_crews"].get(order["crew_id"])
                if order.get("crew_id") else None)
        if crew is not None:
            crew["open_order_count"] = max(0, crew["open_order_count"] - 1)
            recompute_crew_status(crew)
            touch(crew)
    leak = STORE["leaks"].get(order["leak_id"])
    if leak is not None and leak["status"] == "REPAIR_SCHEDULED":
        leak["status"] = "OPEN"
        touch(leak)
    return success(ser_order(order))


@bp.post("/repair-orders/<oid>/apply-permit")
@require_roles("ComplianceOfficer")
def apply_permit(oid):
    order = get_or_404("repair_orders", oid)
    d = body()
    permit_number = req_str(d, "permit_number")
    jurisdiction = req_str(d, "jurisdiction")
    expires_at = req_dt(d, "expires_at")
    if order["dispatch_status"] != "PENDING_DISPATCH":
        raise err("ERR_ORDER_NOT_PENDING_DISPATCH",
                  "RepairOrder.dispatch_status != PENDING_DISPATCH", 409)
    if order["excavation_permit_status"] != "PERMIT_REQUIRED":
        raise err("ERR_PERMIT_NOT_REQUIRED",
                  "RepairOrder.excavation_permit_status != PERMIT_REQUIRED",
                  409)
    if any(p["permit_number"] == permit_number
           for p in STORE["excavation_permits"].values()):
        raise bad_request("permit_number must be unique")
    permit = make_entity()
    permit.update({"repair_order_id": order["id"],
                   "permit_number": permit_number, "jurisdiction": jurisdiction,
                   "applied_at": now(), "granted_at": None,
                   "expires_at": expires_at, "status": "APPLIED"})
    STORE["excavation_permits"][permit["id"]] = permit
    order["excavation_permit_status"] = "PERMIT_APPLIED"
    touch(order)
    return success(ser_permit(permit), code=201)


@bp.get("/excavation-permits")
@require_roles("ComplianceOfficer", "DispatchCoordinator")
def list_permits():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    order_id = request.args.get("repair_order_id")
    items = sorted_all("excavation_permits")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if order_id is not None:
        items = [p for p in items if p["repair_order_id"] == order_id]
    return list_response(items, ser_permit, limit, offset)


@bp.get("/excavation-permits/<pid>")
@require_roles("ComplianceOfficer", "DispatchCoordinator")
def get_permit(pid):
    return success(ser_permit(get_or_404("excavation_permits", pid)))


@bp.post("/excavation-permits/<pid>/grant")
@require_roles("ComplianceOfficer")
def grant_permit(pid):
    permit = get_or_404("excavation_permits", pid)
    if permit["status"] != "APPLIED":
        raise err("ERR_PERMIT_NOT_APPLIED",
                  "ExcavationPermit.status != APPLIED", 409)
    permit["status"] = "GRANTED"
    permit["granted_at"] = now()
    touch(permit)
    order = STORE["repair_orders"].get(permit["repair_order_id"])
    if order is not None:
        order["excavation_permit_status"] = "PERMIT_GRANTED"
        touch(order)
    return success(ser_permit(permit))


@bp.post("/excavation-permits/<pid>/deny")
@require_roles("ComplianceOfficer")
def deny_permit(pid):
    permit = get_or_404("excavation_permits", pid)
    if permit["status"] != "APPLIED":
        raise err("ERR_PERMIT_NOT_APPLIED",
                  "ExcavationPermit.status != APPLIED", 409)
    permit["status"] = "DENIED"
    touch(permit)
    order = STORE["repair_orders"].get(permit["repair_order_id"])
    if order is not None:
        order["excavation_permit_status"] = "PERMIT_DENIED"
        touch(order)
    return success(ser_permit(permit))
