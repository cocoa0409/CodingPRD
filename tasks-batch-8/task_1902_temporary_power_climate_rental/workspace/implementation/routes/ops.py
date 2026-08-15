"""Permits, service visits, telemetry events, incidents, logical clock
(PRD 2.5, 3.5-3.8)."""
from decimal import Decimal

from flask import Blueprint, request

from auth import auth, body, check_customer_owns, customer_scope_filter, get_or_404, require_roles
from calc import (
    CONTRACT_TERMINAL,
    INCIDENT_TERMINAL,
    PERMIT_TERMINAL,
    VISIT_TERMINAL,
    finalize_line,
    quote_expiry_sweep,
    sla_evaluation,
    technician_conflict,
)
from db import DB, incident_out, permit_out, telemetry_out, touch, visit_out
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_FORBIDDEN,
    ERR_INSUFFICIENT_TANK_FUEL,
    ERR_INVALID_DATE_RANGE,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_NOT_OWNER,
    ERR_PERMIT_REVIEW_EXHAUSTED,
    ERR_REFERENCE_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STANDBY_CONTRACT_REQUIRED,
    ERR_TANK_CAPACITY_EXCEEDED,
    ERR_TECHNICIAN_SCHEDULE_CONFLICT,
    ERR_UNIT_CONTRACT_MISMATCH,
    ERR_VALIDATION,
    raise_err,
)
from response import success_object
from routes.common import paginate
from util import as_decimal, as_int, fmt_ts, new_id, now, parse_ts, set_now

bp = Blueprint("ops", __name__)

PERMIT_TYPES = {"EMISSIONS", "NOISE"}
VISIT_TYPES = {"TECHNICIAN", "FUEL_DELIVERY", "EMERGENCY"}
EVENT_TYPES = {"RUNTIME", "FUEL_BURN", "FUEL_DELIVERY", "FUEL_PUMP_OUT"}
INCIDENT_TYPES = {"DAMAGE", "SPILL"}
UNIT_EVENT_TYPES = {"RUNTIME", "FUEL_BURN"}
SITE_EVENT_TYPES = {"FUEL_DELIVERY", "FUEL_PUMP_OUT"}


# ---------------------------------------------------------------------------
# Permits (PRD 3.5)
# ---------------------------------------------------------------------------

@bp.post("/power-rental/permits")
def create_permit():
    uid, role = auth()
    require_roles(role, ["SalesEngineer"])
    b = body()
    contract_id = b.get("contract_id")
    permit_type = b.get("permit_type")
    if contract_id is not None and contract_id not in DB.contracts:
        raise_err(ERR_REFERENCE_NOT_FOUND, "contract_id references a non-existent contract.")
    contract = DB.contracts.get(contract_id) if contract_id is not None else None
    if contract is not None:
        if contract["status"] in CONTRACT_TERMINAL:
            raise_err(ERR_ALREADY_TERMINAL, "Contract is terminal.")
        if contract["status"] not in ("CONFIRMED", "MOBILIZING"):
            raise_err(ERR_INVALID_STATE, "Permits require a CONFIRMED or MOBILIZING contract.")
    if contract_id is None:
        raise_err(ERR_VALIDATION, "contract_id is required.")
    if permit_type not in PERMIT_TYPES:
        raise_err(ERR_VALIDATION, "permit_type must be EMISSIONS or NOISE.")
    site = DB.sites[contract["site_id"]]
    ts = now()
    rec = {
        "id": new_id(),
        "contract_id": contract_id,
        "permit_type": permit_type,
        "jurisdiction_code": site["jurisdiction_code"],
        "status": "DRAFT",
        "review_rounds": 0,
        "submitted_at": None,
        "decided_at": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": DB.next_seq(),
    }
    DB.permits[rec["id"]] = rec
    return success_object(permit_out(rec), status=201)


@bp.get("/power-rental/permits/<pid>")
def get_permit(pid):
    uid, role = auth()
    require_roles(role, ["SalesEngineer", "DepotManager"])
    rec = get_or_404(DB.permits, pid, "permit")
    return success_object(permit_out(rec))


@bp.get("/power-rental/permits")
def list_permits():
    uid, role = auth()
    require_roles(role, ["SalesEngineer", "DepotManager"])
    records = list(DB.permits.values())
    if request.args.get("contract_id") is not None:
        records = [r for r in records if r["contract_id"] == request.args.get("contract_id")]
    if request.args.get("status") is not None:
        records = [r for r in records if r["status"] == request.args.get("status")]
    return paginate(records, permit_out)


def _permit_action(pid):
    uid, role = auth()
    require_roles(role, ["SalesEngineer"])
    permit = get_or_404(DB.permits, pid, "permit")
    if permit["status"] in PERMIT_TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL, "Permit %s is already APPROVED." % pid)
    return permit


@bp.post("/power-rental/permits/<pid>/submit")
def submit_permit(pid):
    permit = _permit_action(pid)
    if permit["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Only a DRAFT permit can be submitted.")
    ts = now()
    permit["review_rounds"] += 1
    permit["submitted_at"] = ts
    permit["status"] = "SUBMITTED"
    touch(permit, ts)
    return success_object(permit_out(permit))


@bp.post("/power-rental/permits/<pid>/record-decision")
def record_decision(pid):
    permit = _permit_action(pid)
    if permit["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Only a SUBMITTED permit can receive a decision.")
    outcome = body().get("outcome")
    if outcome not in ("APPROVED", "REJECTED"):
        raise_err(ERR_VALIDATION, "outcome must be APPROVED or REJECTED.")
    permit["status"] = outcome
    permit["decided_at"] = now()
    touch(permit, now())
    return success_object(permit_out(permit))


@bp.post("/power-rental/permits/<pid>/resubmit")
def resubmit_permit(pid):
    permit = _permit_action(pid)
    if permit["status"] != "REJECTED":
        raise_err(ERR_INVALID_STATE, "Only a REJECTED permit can be resubmitted.")
    if permit["review_rounds"] >= 3:
        raise_err(ERR_PERMIT_REVIEW_EXHAUSTED, "Permit review rounds exhausted (>= 3).")
    ts = now()
    permit["review_rounds"] += 1
    permit["submitted_at"] = ts
    permit["status"] = "SUBMITTED"
    touch(permit, ts)
    return success_object(permit_out(permit))


# ---------------------------------------------------------------------------
# Service visits (PRD 3.7)
# ---------------------------------------------------------------------------

@bp.post("/power-rental/service-visits")
def create_visit():
    uid, role = auth()
    require_roles(role, ["FleetDispatcher", "Customer"])
    b = body()
    visit_type = b.get("visit_type")
    contract_id = b.get("contract_id")
    contract = DB.contracts.get(contract_id) if contract_id is not None else None
    # Tier 2: Customers request EMERGENCY only; dispatchers schedule the rest.
    if role == "Customer" and visit_type is not None and visit_type != "EMERGENCY":
        raise_err(ERR_FORBIDDEN, "Customers may only request EMERGENCY dispatches.")
    if role == "FleetDispatcher" and visit_type is not None and visit_type == "EMERGENCY":
        raise_err(ERR_FORBIDDEN, "FleetDispatcher may not request EMERGENCY dispatches.")
    if role == "Customer" and contract is not None:
        check_customer_owns(contract["customer_id"], uid)
    # Tier 3: body FK existence.
    if contract_id is not None and contract is None:
        raise_err(ERR_REFERENCE_NOT_FOUND, "contract_id references a non-existent contract.")
    # Tier 4: EMERGENCY contract-state gate.
    if visit_type == "EMERGENCY" and contract is not None:
        if contract["status"] in CONTRACT_TERMINAL:
            raise_err(ERR_ALREADY_TERMINAL, "Contract is terminal.")
        if contract["status"] not in ("ON_RENT", "SUSPENDED"):
            raise_err(ERR_INVALID_STATE, "EMERGENCY visits require an ON_RENT or SUSPENDED contract.")
    start = parse_ts(b.get("scheduled_start")) if b.get("scheduled_start") is not None else None
    end = parse_ts(b.get("scheduled_end")) if b.get("scheduled_end") is not None else None
    technician = b.get("assigned_technician_id")
    # Tier 6: buffered technician overlap at creation (well-formed windows only).
    if (
        technician is not None
        and visit_type is not None and visit_type != "EMERGENCY"
        and start is not None and end is not None and start < end
    ):
        if technician_conflict(technician, start, end):
            raise_err(ERR_TECHNICIAN_SCHEDULE_CONFLICT, "Technician buffered window intersects another visit.")
    # Tier 7: payload well-formedness and conditional fields.
    if visit_type not in VISIT_TYPES:
        raise_err(ERR_VALIDATION, "visit_type must be TECHNICIAN, FUEL_DELIVERY, or EMERGENCY.")
    if contract_id is None:
        raise_err(ERR_VALIDATION, "contract_id is required.")
    if visit_type == "EMERGENCY":
        if b.get("scheduled_start") is not None or b.get("scheduled_end") is not None:
            raise_err(ERR_VALIDATION, "EMERGENCY visits carry no scheduled window.")
    else:
        if b.get("scheduled_start") is None or b.get("scheduled_end") is None:
            raise_err(ERR_VALIDATION, "scheduled_start and scheduled_end are required for non-EMERGENCY visits.")
        if start is None or end is None:
            raise_err(ERR_VALIDATION, "scheduled window must be ISO 8601 timestamps.")
    fuel_qty = b.get("fuel_quantity_liters")
    fuel_qty_d = as_decimal(fuel_qty) if fuel_qty is not None else None
    if visit_type == "FUEL_DELIVERY":
        if fuel_qty_d is None or fuel_qty_d <= 0:
            raise_err(ERR_VALIDATION, "fuel_quantity_liters is required and must be positive for FUEL_DELIVERY.")
    elif fuel_qty is not None:
        raise_err(ERR_VALIDATION, "fuel_quantity_liters applies only to FUEL_DELIVERY visits.")
    if visit_type != "EMERGENCY" and start is not None and end is not None and not start < end:
        raise_err(ERR_INVALID_DATE_RANGE, "scheduled_start must be strictly before scheduled_end.")
    if visit_type == "EMERGENCY":
        customer = DB.customers[contract["customer_id"]]
        if not customer["standby_contract"]:
            raise_err(ERR_STANDBY_CONTRACT_REQUIRED, "EMERGENCY dispatch requires a standby agreement.")
    ts = now()
    rec = {
        "id": new_id(),
        "contract_id": contract_id,
        "visit_type": visit_type,
        "status": "SCHEDULED",
        "scheduled_start": start if visit_type != "EMERGENCY" else None,
        "scheduled_end": end if visit_type != "EMERGENCY" else None,
        "assigned_technician_id": technician,
        "fuel_quantity_liters": fuel_qty_d if visit_type == "FUEL_DELIVERY" else None,
        "requested_at": ts if visit_type == "EMERGENCY" else None,
        "dispatched_at": None,
        "arrived_at": None,
        "response_minutes": None,
        "sla_met": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": DB.next_seq(),
    }
    DB.visits[rec["id"]] = rec
    return success_object(visit_out(rec), status=201)


@bp.get("/power-rental/service-visits/<vid>")
def get_visit(vid):
    uid, role = auth()
    require_roles(role, ["FleetDispatcher", "FieldTechnician", "DepotManager", "SalesEngineer", "Customer"])
    rec = DB.visits.get(vid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "No service visit exists with id %s." % vid)
    if role == "Customer":
        contract = DB.contracts.get(rec["contract_id"])
        check_customer_owns(contract["customer_id"] if contract else None, uid)
    return success_object(visit_out(rec))


@bp.get("/power-rental/service-visits")
def list_visits():
    uid, role = auth()
    require_roles(role, ["FleetDispatcher", "FieldTechnician", "DepotManager", "SalesEngineer", "Customer"])
    records = list(DB.visits.values())
    scoped = customer_scope_filter(role, uid)
    if scoped is not None:
        records = [
            r for r in records
            if DB.contracts.get(r["contract_id"]) is not None
            and DB.contracts[r["contract_id"]]["customer_id"] == scoped
        ]
    if request.args.get("contract_id") is not None:
        records = [r for r in records if r["contract_id"] == request.args.get("contract_id")]
    if request.args.get("assigned_technician_id") is not None:
        records = [r for r in records if r["assigned_technician_id"] == request.args.get("assigned_technician_id")]
    if request.args.get("status") is not None:
        records = [r for r in records if r["status"] == request.args.get("status")]
    if request.args.get("visit_type") is not None:
        records = [r for r in records if r["visit_type"] == request.args.get("visit_type")]
    return paginate(records, visit_out)


def _visit_action(vid, allowed_roles):
    uid, role = auth()
    require_roles(role, allowed_roles)
    visit = get_or_404(DB.visits, vid, "service visit")
    return uid, visit


@bp.post("/power-rental/service-visits/<vid>/dispatch")
def dispatch_visit(vid):
    uid, visit = _visit_action(vid, ["FleetDispatcher"])
    if visit["status"] in VISIT_TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL, "Visit %s is terminal." % vid)
    if visit["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Only a SCHEDULED visit can be dispatched.")
    technician = body().get("assigned_technician_id")
    # Tier 6: buffered overlap for the newly assigned technician.
    if (
        technician is not None
        and visit["scheduled_start"] is not None and visit["scheduled_end"] is not None
        and visit["scheduled_start"] < visit["scheduled_end"]
        and technician_conflict(technician, visit["scheduled_start"], visit["scheduled_end"], exclude_visit_id=vid)
    ):
        raise_err(ERR_TECHNICIAN_SCHEDULE_CONFLICT, "Technician buffered window intersects another visit.")
    if technician is None:
        raise_err(ERR_VALIDATION, "assigned_technician_id is required for dispatch.")
    ts = now()
    visit["assigned_technician_id"] = technician
    visit["dispatched_at"] = ts
    visit["status"] = "DISPATCHED"
    touch(visit, ts)
    return success_object(visit_out(visit))


@bp.post("/power-rental/service-visits/<vid>/arrive")
def arrive_visit(vid):
    uid, visit = _visit_action(vid, ["FieldTechnician"])
    if visit["assigned_technician_id"] != uid:
        raise_err(ERR_NOT_OWNER, "Only the assigned technician may arrive this visit.")
    if visit["status"] in VISIT_TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL, "Visit %s is terminal." % vid)
    if visit["status"] != "DISPATCHED":
        raise_err(ERR_INVALID_STATE, "Only a DISPATCHED visit can be arrived.")
    ts = now()
    visit["arrived_at"] = ts
    if visit["visit_type"] == "EMERGENCY":
        contract = DB.contracts[visit["contract_id"]]
        customer = DB.customers[contract["customer_id"]]
        sla_evaluation(visit, customer)
    visit["status"] = "ON_SITE"
    touch(visit, ts)
    return success_object(visit_out(visit))


@bp.post("/power-rental/service-visits/<vid>/complete")
def complete_visit(vid):
    uid, visit = _visit_action(vid, ["FieldTechnician"])
    if visit["assigned_technician_id"] != uid:
        raise_err(ERR_NOT_OWNER, "Only the assigned technician may complete this visit.")
    if visit["status"] in VISIT_TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL, "Visit %s is terminal." % vid)
    if visit["status"] != "ON_SITE":
        raise_err(ERR_INVALID_STATE, "Only an ON_SITE visit can be completed.")
    contract = DB.contracts[visit["contract_id"]]
    site = DB.sites[contract["site_id"]]
    # Tier 5: tank capacity guard on fuel-delivery completion.
    if visit["visit_type"] == "FUEL_DELIVERY":
        if site["tank_level_liters"] + visit["fuel_quantity_liters"] > site["fuel_tank_capacity_liters"]:
            raise_err(ERR_TANK_CAPACITY_EXCEEDED, "Fuel delivery would exceed tank capacity.")
    ts = now()
    if visit["visit_type"] == "FUEL_DELIVERY":
        event = {
            "id": new_id(),
            "equipment_unit_id": None,
            "contract_id": visit["contract_id"],
            "event_type": "FUEL_DELIVERY",
            "value": visit["fuel_quantity_liters"],
            "recorded_at": ts,
            "created_at": ts,
            "_seq": DB.next_seq(),
        }
        DB.telemetry[event["id"]] = event
        site["tank_level_liters"] += visit["fuel_quantity_liters"]
    visit["status"] = "COMPLETED"
    touch(visit, ts)
    return success_object(visit_out(visit))


@bp.post("/power-rental/service-visits/<vid>/cancel")
def cancel_visit(vid):
    uid, visit = _visit_action(vid, ["FleetDispatcher"])
    if visit["status"] in VISIT_TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL, "Visit %s is terminal." % vid)
    if visit["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Only a SCHEDULED visit can be cancelled.")
    visit["status"] = "CANCELLED"
    touch(visit, now())
    return success_object(visit_out(visit))


# ---------------------------------------------------------------------------
# Telemetry (PRD 3.6) — append-only; id + created_at only.
# ---------------------------------------------------------------------------

@bp.post("/power-rental/telemetry-events")
def create_telemetry():
    uid, role = auth()
    require_roles(role, ["FieldTechnician"])
    b = body()
    contract_id = b.get("contract_id")
    equipment_unit_id = b.get("equipment_unit_id")
    event_type = b.get("event_type")
    contract = DB.contracts.get(contract_id) if contract_id is not None else None
    # Tier 3: body FK existence.
    if contract_id is not None and contract is None:
        raise_err(ERR_REFERENCE_NOT_FOUND, "contract_id references a non-existent contract.")
    if equipment_unit_id is not None and equipment_unit_id not in DB.units:
        raise_err(ERR_REFERENCE_NOT_FOUND, "equipment_unit_id references a non-existent unit.")
    value = as_decimal(b.get("value"))
    site = DB.sites[contract["site_id"]] if contract is not None else None
    # Tier 5: delivery capacity guard.
    if event_type == "FUEL_DELIVERY" and site is not None and value is not None and value > 0:
        if site["tank_level_liters"] + value > site["fuel_tank_capacity_liters"]:
            raise_err(ERR_TANK_CAPACITY_EXCEEDED, "Delivery would raise the tank above capacity.")
    # Tier 7: payload well-formedness.
    if contract_id is None:
        raise_err(ERR_VALIDATION, "contract_id is required.")
    if event_type not in EVENT_TYPES:
        raise_err(ERR_VALIDATION, "event_type must be RUNTIME, FUEL_BURN, FUEL_DELIVERY, or FUEL_PUMP_OUT.")
    if value is None or value <= 0:
        raise_err(ERR_VALIDATION, "value must be a positive number.")
    if event_type in UNIT_EVENT_TYPES and equipment_unit_id is None:
        raise_err(ERR_VALIDATION, "equipment_unit_id is required for %s events." % event_type)
    if event_type in SITE_EVENT_TYPES and equipment_unit_id is not None:
        raise_err(ERR_VALIDATION, "equipment_unit_id must be null for %s events." % event_type)
    recorded_at = None
    if b.get("recorded_at") is not None:
        recorded_at = parse_ts(b.get("recorded_at"))
        if recorded_at is None:
            raise_err(ERR_VALIDATION, "recorded_at must be an ISO 8601 timestamp.")
    ts = now()
    if recorded_at is not None and recorded_at > ts:
        raise_err(ERR_INVALID_DATE_RANGE, "recorded_at may not lie in the future.")
    if event_type == "FUEL_PUMP_OUT" and value > site["tank_level_liters"]:
        raise_err(ERR_INSUFFICIENT_TANK_FUEL, "Pump-out exceeds the current tank level.")
    # Tier 8: the named unit must sit on an active equipment line of the contract.
    if equipment_unit_id is not None:
        active = any(
            l["contract_id"] == contract_id
            and l["line_type"] == "EQUIPMENT"
            and l["equipment_unit_id"] == equipment_unit_id
            and l["status"] in ("PENDING", "ON_RENT")
            for l in DB.lines.values()
        )
        if not active:
            raise_err(ERR_UNIT_CONTRACT_MISMATCH, "Unit is not on an active EQUIPMENT line of this contract.")
    if recorded_at is None:
        recorded_at = ts
    rec = {
        "id": new_id(),
        "equipment_unit_id": equipment_unit_id,
        "contract_id": contract_id,
        "event_type": event_type,
        "value": value,
        "recorded_at": recorded_at,
        "created_at": ts,
        "_seq": DB.next_seq(),
    }
    DB.telemetry[rec["id"]] = rec
    if event_type == "RUNTIME":
        DB.units[equipment_unit_id]["runtime_hours_total"] += value
    elif event_type == "FUEL_BURN":
        DB.units[equipment_unit_id]["fuel_consumed_liters_total"] += value
    elif event_type == "FUEL_DELIVERY":
        site["tank_level_liters"] += value
    else:  # FUEL_PUMP_OUT
        site["tank_level_liters"] -= value
    return success_object(telemetry_out(rec), status=201)


@bp.get("/power-rental/telemetry-events/<tid>")
def get_telemetry(tid):
    uid, role = auth()
    require_roles(role, ["FieldTechnician", "FleetDispatcher", "DepotManager", "SalesEngineer"])
    rec = get_or_404(DB.telemetry, tid, "telemetry event")
    return success_object(telemetry_out(rec))


@bp.get("/power-rental/telemetry-events")
def list_telemetry():
    uid, role = auth()
    require_roles(role, ["FieldTechnician", "FleetDispatcher", "DepotManager", "SalesEngineer"])
    records = list(DB.telemetry.values())
    if request.args.get("equipment_unit_id") is not None:
        records = [r for r in records if r["equipment_unit_id"] == request.args.get("equipment_unit_id")]
    if request.args.get("contract_id") is not None:
        records = [r for r in records if r["contract_id"] == request.args.get("contract_id")]
    if request.args.get("event_type") is not None:
        records = [r for r in records if r["event_type"] == request.args.get("event_type")]
    return paginate(records, telemetry_out)


# ---------------------------------------------------------------------------
# Incidents (PRD 3.8)
# ---------------------------------------------------------------------------

@bp.post("/power-rental/incidents")
def create_incident():
    uid, role = auth()
    require_roles(role, ["Customer", "SalesEngineer"])
    b = body()
    contract_id = b.get("contract_id")
    equipment_unit_id = b.get("equipment_unit_id")
    incident_type = b.get("incident_type")
    contract = DB.contracts.get(contract_id) if contract_id is not None else None
    # Tier 2 ownership: Customers report only on their own contracts.
    if role == "Customer" and contract is not None:
        check_customer_owns(contract["customer_id"], uid)
    # Tier 3: body FK existence.
    if contract_id is not None and contract is None:
        raise_err(ERR_REFERENCE_NOT_FOUND, "contract_id references a non-existent contract.")
    if equipment_unit_id is not None and equipment_unit_id not in DB.units:
        raise_err(ERR_REFERENCE_NOT_FOUND, "equipment_unit_id references a non-existent unit.")
    # Tier 4: contract must stand ON_RENT or OFF_HIRE.
    if contract is not None:
        if contract["status"] in CONTRACT_TERMINAL:
            raise_err(ERR_ALREADY_TERMINAL, "Contract is terminal.")
        if contract["status"] not in ("ON_RENT", "OFF_HIRE"):
            raise_err(ERR_INVALID_STATE, "Incidents require an ON_RENT or OFF_HIRE contract.")
    # Tier 7: payload well-formedness and conditional spill volume.
    if contract_id is None:
        raise_err(ERR_VALIDATION, "contract_id is required.")
    if equipment_unit_id is None:
        raise_err(ERR_VALIDATION, "equipment_unit_id is required.")
    if incident_type not in INCIDENT_TYPES:
        raise_err(ERR_VALIDATION, "incident_type must be DAMAGE or SPILL.")
    spill_volume = b.get("spill_volume_liters")
    spill_volume_d = as_decimal(spill_volume) if spill_volume is not None else None
    if incident_type == "SPILL":
        if spill_volume_d is None or spill_volume_d <= 0:
            raise_err(ERR_VALIDATION, "spill_volume_liters is required and must be positive for SPILL.")
    elif spill_volume is not None:
        raise_err(ERR_VALIDATION, "spill_volume_liters applies only to SPILL incidents.")
    # Tier 8: unit must sit on an active equipment line of the contract.
    active = any(
        l["contract_id"] == contract_id
        and l["line_type"] == "EQUIPMENT"
        and l["equipment_unit_id"] == equipment_unit_id
        and l["status"] in ("PENDING", "ON_RENT")
        for l in DB.lines.values()
    )
    if not active:
        raise_err(ERR_UNIT_CONTRACT_MISMATCH, "Unit is not on an active EQUIPMENT line of this contract.")
    ts = now()
    rec = {
        "id": new_id(),
        "contract_id": contract_id,
        "equipment_unit_id": equipment_unit_id,
        "incident_type": incident_type,
        "spill_volume_liters": spill_volume_d if incident_type == "SPILL" else None,
        "notes": b.get("notes"),
        "status": "REPORTED",
        "assessed_charge_cents": None,
        "assessed_by": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": DB.next_seq(),
    }
    DB.incidents[rec["id"]] = rec
    # SPILL three-link cascade (PRD 3.8).
    if incident_type == "SPILL":
        unit = DB.units[equipment_unit_id]
        if unit["status"] == "DEPLOYED":
            # Link 1: quarantine the unit.
            unit["status"] = "QUARANTINED"
            touch(unit, ts)
            # Link 2: suspend the parent contract.
            if contract["status"] == "ON_RENT":
                contract["status"] = "SUSPENDED"
                touch(contract, ts)
                # Link 3: cancel every SCHEDULED visit for the contract.
                for v in DB.visits.values():
                    if v["contract_id"] == contract_id and v["status"] == "SCHEDULED":
                        v["status"] = "CANCELLED"
                        touch(v, ts)
    return success_object(incident_out(rec), status=201)


@bp.get("/power-rental/incidents/<iid>")
def get_incident(iid):
    uid, role = auth()
    require_roles(role, ["ClaimsAssessor", "DepotManager", "SalesEngineer", "Customer"])
    rec = DB.incidents.get(iid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "No incident exists with id %s." % iid)
    if role == "Customer":
        contract = DB.contracts.get(rec["contract_id"])
        check_customer_owns(contract["customer_id"] if contract else None, uid)
    return success_object(incident_out(rec))


@bp.get("/power-rental/incidents")
def list_incidents():
    uid, role = auth()
    require_roles(role, ["ClaimsAssessor", "DepotManager", "SalesEngineer", "Customer"])
    records = list(DB.incidents.values())
    scoped = customer_scope_filter(role, uid)
    if scoped is not None:
        records = [
            r for r in records
            if DB.contracts.get(r["contract_id"]) is not None
            and DB.contracts[r["contract_id"]]["customer_id"] == scoped
        ]
    if request.args.get("contract_id") is not None:
        records = [r for r in records if r["contract_id"] == request.args.get("contract_id")]
    if request.args.get("equipment_unit_id") is not None:
        records = [r for r in records if r["equipment_unit_id"] == request.args.get("equipment_unit_id")]
    if request.args.get("status") is not None:
        records = [r for r in records if r["status"] == request.args.get("status")]
    return paginate(records, incident_out)


@bp.post("/power-rental/incidents/<iid>/assess")
def assess_incident(iid):
    uid, role = auth()
    require_roles(role, ["ClaimsAssessor"])
    incident = get_or_404(DB.incidents, iid, "incident")
    if incident["status"] in INCIDENT_TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL, "Incident %s is terminal." % iid)
    if incident["status"] != "REPORTED":
        raise_err(ERR_INVALID_STATE, "Only a REPORTED incident can be assessed.")
    charge = as_int(body().get("assessed_charge_cents"))
    if charge is None or charge < 0:
        raise_err(ERR_VALIDATION, "assessed_charge_cents must be a non-negative integer.")
    ts = now()
    incident["assessed_charge_cents"] = charge
    incident["assessed_by"] = uid
    incident["status"] = "ASSESSED"
    touch(incident, ts)
    if incident["incident_type"] == "SPILL":
        unit = DB.units.get(incident["equipment_unit_id"])
        contract = DB.contracts.get(incident["contract_id"])
        if unit is not None and unit["status"] == "QUARANTINED":
            # Resolve the freeze: quarantine -> maintenance queue.
            unit["status"] = "MAINTENANCE"
            touch(unit, ts)
            # The quarantined unit's ON_RENT line finalizes to this moment.
            for line in DB.lines.values():
                if (
                    line["contract_id"] == incident["contract_id"]
                    and line["equipment_unit_id"] == unit["id"]
                    and line["status"] == "ON_RENT"
                ):
                    finalize_line(line, ts)
        if contract is not None and contract["status"] == "SUSPENDED":
            contract["status"] = "ON_RENT"
            touch(contract, ts)
    return success_object(incident_out(incident))


@bp.post("/power-rental/incidents/<iid>/waive")
def waive_incident(iid):
    uid, role = auth()
    require_roles(role, ["DepotManager"])
    incident = get_or_404(DB.incidents, iid, "incident")
    # Tier 2 segregation of duties: waver must differ from the assessor.
    if incident["assessed_by"] is not None and incident["assessed_by"] == uid:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "The assessor may not waive their own assessment.")
    if incident["status"] in INCIDENT_TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL, "Incident %s is terminal." % iid)
    if incident["status"] != "ASSESSED":
        raise_err(ERR_INVALID_STATE, "Only an ASSESSED incident can be waived.")
    incident["status"] = "WAIVED"
    touch(incident, now())
    return success_object(incident_out(incident))


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5)
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    uid, role = auth()
    require_roles(role, ["PlatformAdmin"])
    target = parse_ts(body().get("to_iso8601"))
    if target is None:
        raise_err(ERR_VALIDATION, "to_iso8601 must be an ISO 8601 timestamp.")
    set_now(target)
    quote_expiry_sweep(target)
    return success_object({"current_utc": fmt_ts(target)})
