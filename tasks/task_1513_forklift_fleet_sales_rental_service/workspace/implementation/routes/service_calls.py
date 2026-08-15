"""Service call endpoints."""
from datetime import timedelta
from flask import Blueprint, request

import store
from auth import authenticate, authorize, ALL_ROLES
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_UNAUTHORIZED, ERR_OPERATOR_CERT_EXPIRED, ERR_TECHNICIAN_INACTIVE,
    ERR_VAN_STOCK_INSUFFICIENT, ERR_DISPATCH_WINDOW_OVERLAP,
)
from util import (
    body_json, req_str, req_datetime, new_record, bump,
    success_object, list_response, get_or_404,
)
import services

bp = Blueprint("service_calls", __name__)


def _parse_parts(raw, name):
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise_err(ERR_INVALID_REQUEST, "%s must be a list" % name)
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise_err(ERR_INVALID_REQUEST, "each %s entry must be an object" % name)
        pn = entry.get("part_number")
        qty = entry.get("qty")
        if not isinstance(pn, str):
            raise_err(ERR_INVALID_REQUEST, "part_number must be a string")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 0:
            raise_err(ERR_INVALID_REQUEST, "qty must be an integer >= 0")
        out.append({"part_number": pn, "qty": qty})
    return out


@bp.post("/fleet/service-calls")
def create_service_call():
    _, role = authenticate()
    authorize(role, ["ServiceDispatcher"])
    body = body_json()
    unit_id = req_str(body, "unit_id")
    customer_id = req_str(body, "customer_id")
    call_type = req_str(body, "call_type")
    if call_type not in ("BREAKDOWN", "PM"):
        raise_err(ERR_INVALID_REQUEST, "call_type must be BREAKDOWN or PM")
    priority = req_str(body, "priority")
    if priority not in ("EMERGENCY", "STANDARD"):
        raise_err(ERR_INVALID_REQUEST, "priority must be EMERGENCY or STANDARD")
    operator_id = body.get("operator_id")
    if operator_id is not None and not isinstance(operator_id, str):
        raise_err(ERR_INVALID_REQUEST, "operator_id must be a string or null")
    required_parts = _parse_parts(body.get("required_parts"), "required_parts")
    get_or_404(store.units, unit_id, "Unit")
    get_or_404(store.customers, customer_id, "Customer")
    if operator_id is not None:
        get_or_404(store.operators, operator_id, "Operator")
    rec = new_record()
    rec.update({
        "unit_id": unit_id,
        "customer_id": customer_id,
        "call_type": call_type,
        "priority": priority,
        "operator_id": operator_id,
        "technician_id": None,
        "required_parts": required_parts,
        "used_parts": None,
        "scheduled_start": None,
        "scheduled_end": None,
        "auto_created": False,
        "status": "OPEN",
    })
    store.service_calls[rec["id"]] = rec
    return success_object(services.serialize_service_call(rec), 201)


@bp.get("/fleet/service-calls/<sid>")
def get_service_call(sid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    sc = get_or_404(store.service_calls, sid, "ServiceCall")
    return success_object(services.serialize_service_call(sc), 200)


@bp.get("/fleet/service-calls")
def list_service_calls():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    records = list(store.service_calls.values())
    unit_id = request.args.get("unit_id")
    customer_id = request.args.get("customer_id")
    technician_id = request.args.get("technician_id")
    operator_id = request.args.get("operator_id")
    status = request.args.get("status")
    if unit_id:
        records = [r for r in records if r["unit_id"] == unit_id]
    if customer_id:
        records = [r for r in records if r["customer_id"] == customer_id]
    if technician_id:
        records = [r for r in records if r["technician_id"] == technician_id]
    if operator_id:
        records = [r for r in records if r["operator_id"] == operator_id]
    if status:
        records = [r for r in records if r["status"] == status]
    return list_response(records, services.serialize_service_call)


@bp.post("/fleet/service-calls/<sid>/dispatch")
def dispatch_service_call(sid):
    _, role = authenticate()
    authorize(role, ["ServiceDispatcher"])
    body = body_json()
    technician_id = req_str(body, "technician_id")
    scheduled_start = req_datetime(body, "scheduled_start")
    scheduled_end = req_datetime(body, "scheduled_end")
    if scheduled_end < scheduled_start:
        raise_err(ERR_INVALID_REQUEST, "scheduled_end must be >= scheduled_start")
    sc = get_or_404(store.service_calls, sid, "ServiceCall")
    if sc["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "ServiceCall must be OPEN to dispatch")
    technician = get_or_404(store.technicians, technician_id, "Technician")
    # operator certification check
    if sc.get("operator_id"):
        if not services.operator_has_active_certification(sc["operator_id"]):
            raise_err(ERR_OPERATOR_CERT_EXPIRED, "Operator does not hold an ACTIVE certification")
    # technician active
    if technician["status"] != "ACTIVE":
        raise_err(ERR_TECHNICIAN_INACTIVE, "Technician is INACTIVE")
    # van stock sufficiency
    stock = {e["part_number"]: e["qty"] for e in technician.get("van_stock", [])}
    for req in sc.get("required_parts", []):
        if stock.get(req["part_number"], 0) < req["qty"]:
            raise_err(ERR_VAN_STOCK_INSUFFICIENT, "Van stock cannot cover required_parts")
    # dispatch window overlap: closed interval, +/- 60 min
    new_lo = scheduled_start - timedelta(minutes=60)
    new_hi = scheduled_end + timedelta(minutes=60)
    for other in store.service_calls.values():
        if other["id"] == sc["id"]:
            continue
        if other.get("technician_id") != technician_id:
            continue
        if other["status"] != "DISPATCHED":
            continue
        o_lo = other["scheduled_start"] - timedelta(minutes=60)
        o_hi = other["scheduled_end"] + timedelta(minutes=60)
        # closed-interval intersection
        if new_lo <= o_hi and new_hi >= o_lo:
            raise_err(ERR_DISPATCH_WINDOW_OVERLAP, "Buffered dispatch window overlaps another dispatched call")
    # decrement van stock
    for req in sc.get("required_parts", []):
        if req["qty"] == 0:
            continue
        for entry in technician["van_stock"]:
            if entry["part_number"] == req["part_number"]:
                entry["qty"] -= req["qty"]
                break
    bump(technician)
    # record dispatch fields
    sc["technician_id"] = technician_id
    sc["scheduled_start"] = scheduled_start
    sc["scheduled_end"] = scheduled_end
    sc["status"] = "DISPATCHED"
    # if unit AVAILABLE -> IN_SHOP; remember that we moved it
    unit = store.units.get(sc["unit_id"])
    if unit is not None and unit["availability_status"] == "AVAILABLE":
        unit["availability_status"] = "IN_SHOP"
        sc["_moved_unit_to_shop"] = True
        bump(unit)
    else:
        sc["_moved_unit_to_shop"] = False
    bump(sc)
    return success_object(services.serialize_service_call(sc), 200)


@bp.post("/fleet/service-calls/<sid>/release")
def release_service_call(sid):
    _, role = authenticate()
    authorize(role, ["ServiceDispatcher"])
    sc = get_or_404(store.service_calls, sid, "ServiceCall")
    if sc["status"] != "DISPATCHED":
        raise_err(ERR_INVALID_STATE, "ServiceCall must be DISPATCHED to release")
    technician = store.technicians.get(sc["technician_id"])
    if technician is not None:
        for req in sc.get("required_parts", []):
            if req["qty"] == 0:
                continue
            found = False
            for entry in technician["van_stock"]:
                if entry["part_number"] == req["part_number"]:
                    entry["qty"] += req["qty"]
                    found = True
                    break
            if not found:
                technician["van_stock"].append({"part_number": req["part_number"], "qty": req["qty"]})
        bump(technician)
    sc["technician_id"] = None
    sc["scheduled_start"] = None
    sc["scheduled_end"] = None
    sc["status"] = "OPEN"
    if sc.pop("_moved_unit_to_shop", False):
        unit = store.units.get(sc["unit_id"])
        if unit is not None and unit["availability_status"] == "IN_SHOP":
            unit["availability_status"] = "AVAILABLE"
            bump(unit)
    bump(sc)
    return success_object(services.serialize_service_call(sc), 200)


@bp.post("/fleet/service-calls/<sid>/resolve")
def resolve_service_call(sid):
    uid, role = authenticate()
    authorize(role, ["Technician"])
    body = body_json()
    used_parts = _parse_parts(body.get("used_parts"), "used_parts")
    sc = get_or_404(store.service_calls, sid, "ServiceCall")
    if sc["status"] != "DISPATCHED":
        raise_err(ERR_INVALID_STATE, "ServiceCall must be DISPATCHED to resolve")
    # technician identity: X-User-ID must equal sc.technician_id
    if uid != sc["technician_id"]:
        raise_err(ERR_UNAUTHORIZED, "Only the assigned technician may resolve this call")
    # every used qty <= dispatched qty for that part
    dispatched = {p["part_number"]: p["qty"] for p in sc.get("required_parts", [])}
    for up in used_parts:
        if up["qty"] > dispatched.get(up["part_number"], 0):
            raise_err(ERR_INVALID_REQUEST, "used_parts qty exceeds dispatched qty for part %s" % up["part_number"])
    sc["used_parts"] = used_parts
    sc["status"] = "CLOSED"
    # return unused parts to van
    technician = store.technicians.get(sc["technician_id"])
    if technician is not None:
        used_map = {p["part_number"]: p["qty"] for p in used_parts}
        for req in sc.get("required_parts", []):
            remainder = req["qty"] - used_map.get(req["part_number"], 0)
            if remainder > 0:
                found = False
                for entry in technician["van_stock"]:
                    if entry["part_number"] == req["part_number"]:
                        entry["qty"] += remainder
                        found = True
                        break
                if not found:
                    technician["van_stock"].append({"part_number": req["part_number"], "qty": remainder})
        bump(technician)
    # PM cascade
    unit = store.units.get(sc["unit_id"])
    if sc["call_type"] == "PM" and unit is not None:
        unit["last_pm_hours"] = unit["hour_meter"]
        unit["next_pm_due_hours"] = unit["last_pm_hours"] + unit["pm_interval_hours"]
        # PM resolve does NOT auto-create another call
        unit["maintenance_posture"] = "PM_OK"
    if sc.pop("_moved_unit_to_shop", False):
        if unit is not None and unit["availability_status"] == "IN_SHOP":
            unit["availability_status"] = "AVAILABLE"
    if unit is not None:
        bump(unit)
    bump(sc)
    return success_object(services.serialize_service_call(sc), 200)
