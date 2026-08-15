"""ServiceCall endpoints (PRD 3.7): homeowner-originated calls, dispatch with
tier-based provisional estimates and entrapment SLA, arrival, resolution with
final billing, cancellation with visit restoration."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g

import db
from errors import (
    ApiError, ERR_INVALID_DATE_RANGE, ERR_NO_VISITS_REMAINING,
    ERR_NOT_ASSIGNED_TECHNICIAN, ERR_SERVICE_CALL_NOT_FOUND,
    ERR_SERVICE_CALL_STATE_FORBIDS, ERR_TECHNICIAN_NOT_ACTIVE,
    ERR_TECHNICIAN_NOT_CERTIFIED, ERR_TECHNICIAN_NOT_FOUND,
    ERR_UNIT_NOT_FOUND, state_forbids,
)
from middleware import (
    HOMEOWNER, INSTALLER, PROJECT_COORDINATOR, ALL_ROLES, require_roles,
)
from response import ok
from routes.common import get_or_404, list_endpoint, require_property_ownership
from services import calc, cascade
from util import dec, get_json_body, serialize, validate_body

bp = Blueprint("service_calls", __name__)

CALL_TYPES = ["MAINTENANCE_VISIT", "REPAIR", "ENTRAPMENT"]
CET_LEVEL = ("CET", "CET_AND_QEI")

CREATE_SPEC = {
    "unit_id": ("string", True, None),
    "call_type": ("enum", True, CALL_TYPES),
    "description": ("string", False, None),
}


def _attached_contract(call):
    if call.get("contract_id"):
        return db.contracts.get(call["contract_id"])
    return None


@bp.post("/api/service-calls")
@require_roles(HOMEOWNER)
def create_service_call():
    vals = validate_body(get_json_body(), CREATE_SPEC)
    unit = get_or_404(db.units, vals["unit_id"], ERR_UNIT_NOT_FOUND, "Unit")
    # auto-attach the unit's ACTIVE contract; ad-hoc (null) when none exists
    active = [c for c in db.contracts.values() if c["unit_id"] == unit["id"] and c["status"] == "ACTIVE"]
    contract_id = active[0]["id"] if active else None
    rec = db.new_record({
        "unit_id": unit["id"],
        "contract_id": contract_id,
        "technician_id": None,
        "call_type": vals["call_type"],
        "description": vals.get("description"),
        "reported_at": db.now(),
        "arrived_at": None,
        "resolved_at": None,
        "sla_deadline": None,
        "sla_breached": None,
        "provisional_estimate": None,
        "final_billable": None,
        "status": "OPEN",
    })
    rec["_visit_charged_contract_id"] = None
    db.service_calls[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.get("/api/service-calls")
@require_roles(*ALL_ROLES)
def list_service_calls():
    return list_endpoint(db.service_calls, {
        "unit_id": "unit_id",
        "contract_id": "contract_id",
        "technician_id": "technician_id",
        "call_type": "call_type",
        "status": "status",
    })


@bp.get("/api/service-calls/<serviceCallId>")
@require_roles(*ALL_ROLES)
def get_service_call(serviceCallId):
    rec = get_or_404(db.service_calls, serviceCallId, ERR_SERVICE_CALL_NOT_FOUND, "ServiceCall")
    return ok(serialize(rec))


@bp.post("/api/service-calls/<serviceCallId>/dispatch")
@require_roles(PROJECT_COORDINATOR)
def dispatch_service_call(serviceCallId):
    call = get_or_404(db.service_calls, serviceCallId, ERR_SERVICE_CALL_NOT_FOUND, "ServiceCall")
    vals = validate_body(get_json_body(), {"technician_id": ("string", True, None)})
    technician = get_or_404(db.technicians, vals["technician_id"], ERR_TECHNICIAN_NOT_FOUND, "Technician")
    # state admission (priority 5)
    if call["status"] != "OPEN":
        raise state_forbids(ERR_SERVICE_CALL_STATE_FORBIDS, "ServiceCall")
    # certification (priority 6): REPAIR / ENTRAPMENT require CET-level
    if call["call_type"] in ("REPAIR", "ENTRAPMENT") and technician["certification"] not in CET_LEVEL:
        raise ApiError(ERR_TECHNICIAN_NOT_CERTIFIED, 403, "REPAIR and ENTRAPMENT dispatch require CET-level certification")
    # referenced technician must be ACTIVE (priority 8)
    if technician["status"] != "ACTIVE":
        raise ApiError(ERR_TECHNICIAN_NOT_ACTIVE, 409, "Referenced technician is INACTIVE")
    contract = _attached_contract(call)
    # visit conservation (priority 9): MAINTENANCE_VISIT consumes a contract visit
    if call["call_type"] == "MAINTENANCE_VISIT" and contract is not None:
        if contract["visits_consumed"] >= contract["included_visits"]:
            raise ApiError(ERR_NO_VISITS_REMAINING, 409, "Contract has no visits remaining for the current contract year")
    call["technician_id"] = technician["id"]
    call["status"] = "DISPATCHED"
    if call["call_type"] == "MAINTENANCE_VISIT" and contract is not None:
        contract["visits_consumed"] += 1
        call["_visit_charged_contract_id"] = contract["id"]
        db.touch(contract)
    # commercial baseline: tier-flat provisional estimate; entrapment SLA deadline
    call["provisional_estimate"] = calc.provisional_estimate(contract)
    if call["call_type"] == "ENTRAPMENT":
        sla_minutes = contract["entrapment_sla_minutes"] if contract is not None else calc.AD_HOC_SLA_MINUTES
        call["sla_deadline"] = call["reported_at"] + timedelta(minutes=sla_minutes)
    db.touch(call)
    return ok(serialize(call))


@bp.post("/api/service-calls/<serviceCallId>/arrive")
@require_roles(INSTALLER)
def arrive_service_call(serviceCallId):
    call = get_or_404(db.service_calls, serviceCallId, ERR_SERVICE_CALL_NOT_FOUND, "ServiceCall")
    if call["status"] != "DISPATCHED":
        raise state_forbids(ERR_SERVICE_CALL_STATE_FORBIDS, "ServiceCall")
    # identity binding (priority 7): only the dispatched technician
    if g.user_id != call["technician_id"]:
        raise ApiError(ERR_NOT_ASSIGNED_TECHNICIAN, 403, "Caller is not the dispatched technician")
    call["arrived_at"] = db.now()
    call["status"] = "ON_SITE"
    # SLA breach: strictly greater than the SLA minutes; equality is compliant
    if call["call_type"] == "ENTRAPMENT" and call["sla_deadline"] is not None:
        call["sla_breached"] = call["arrived_at"] > call["sla_deadline"]
    db.touch(call)
    return ok(serialize(call))


@bp.post("/api/service-calls/<serviceCallId>/resolve")
@require_roles(INSTALLER)
def resolve_service_call(serviceCallId):
    call = get_or_404(db.service_calls, serviceCallId, ERR_SERVICE_CALL_NOT_FOUND, "ServiceCall")
    vals = validate_body(get_json_body(), {
        "resolution_notes": ("string", True, None),
        "parts_cost": ("money", False, None),
    })
    if call["status"] != "ON_SITE":
        raise state_forbids(ERR_SERVICE_CALL_STATE_FORBIDS, "ServiceCall")
    if g.user_id != call["technician_id"]:
        raise ApiError(ERR_NOT_ASSIGNED_TECHNICIAN, 403, "Caller is not the dispatched technician")
    resolved_at = db.now()
    # resolved_at must not precede arrived_at
    if resolved_at < call["arrived_at"]:
        raise ApiError(ERR_INVALID_DATE_RANGE, 422, "resolved_at must not precede arrived_at")
    call["resolved_at"] = resolved_at
    parts_cost = vals.get("parts_cost", Decimal("0"))
    call["final_billable"] = calc.final_billable(call, _attached_contract(call), parts_cost)
    call["status"] = "RESOLVED"
    db.touch(call)
    return ok(serialize(call))


@bp.post("/api/service-calls/<serviceCallId>/cancel")
@require_roles(HOMEOWNER, PROJECT_COORDINATOR)
def cancel_service_call(serviceCallId):
    call = get_or_404(db.service_calls, serviceCallId, ERR_SERVICE_CALL_NOT_FOUND, "ServiceCall")
    # state admission (priority 5): only OPEN / DISPATCHED
    if call["status"] not in ("OPEN", "DISPATCHED"):
        raise state_forbids(ERR_SERVICE_CALL_STATE_FORBIDS, "ServiceCall")
    # identity binding (priority 7): a homeowner caller must own the property
    if g.role == HOMEOWNER:
        unit = db.units.get(call["unit_id"])
        require_property_ownership(unit["property_id"] if unit else None)
    cascade.cancel_service_call(call)
    return ok(serialize(call))
