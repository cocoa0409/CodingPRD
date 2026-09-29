"""Reference-data routes: agreements, clauses, people, precedents, arbitrators,
the arbitrator strike history and the logical-clock control."""

from flask import Blueprint

import core
from core import (
    ApiError, db, now, base_record, touch, ok, paginated, qp, order_by,
    authenticate, get_body, bad,
    req_string, opt_string, req_enum, opt_enum, req_int, opt_int, req_bool, opt_bool,
    req_dt, opt_dt, req_id, opt_id, req_enum_array,
    ROLE_DIRECTOR, ROLE_ADMIN, READ_ROLES,
)
import derive
from derive import (
    CLAUSE_CATEGORIES, CLASSIFICATIONS, EMPLOYMENT_STATUSES,
    PRECEDENT_OUTCOMES, BINDING_SCOPES, PANEL_SOURCES,
    ser_unit, ser_clause, ser_employee, ser_precedent, ser_arbitrator, ser_strike,
)
import services

bp = Blueprint("config", __name__)
clock_bp = Blueprint("clock", __name__)


# --------------------------------------------------------------------------
# Collective agreements
# --------------------------------------------------------------------------
@bp.post("/bargaining-units")
def create_bargaining_unit():
    authenticate([ROLE_DIRECTOR])
    body = get_body()

    name = req_string(body, "name")
    local_number = req_string(body, "local_number", max_len=32)
    effective = req_dt(body, "contract_effective_date")
    expiry = req_dt(body, "contract_expiry_date")
    if expiry <= effective:
        bad("contract_expiry_date", "must be strictly after contract_effective_date")

    step1 = opt_int(body, "step1_response_days", 10, minimum=1)
    step2 = opt_int(body, "step2_response_days", 15, minimum=1)
    step3 = opt_int(body, "step3_response_days", 20, minimum=1)
    appeal_days = opt_int(body, "appeal_window_days", 7, minimum=1)
    filing_days = opt_int(body, "filing_window_days", 30, minimum=1)
    arbitration_days = opt_int(body, "arbitration_demand_days", 21, minimum=1)
    tolling = opt_bool(body, "tolling_enabled", False)
    director_cents = opt_int(body, "director_authority_cents", 250000, minimum=0)
    negotiator_cents = opt_int(body, "negotiator_authority_cents", 1500000, minimum=0)
    if negotiator_cents <= director_cents:
        bad("negotiator_authority_cents", "must be strictly greater than director_authority_cents")
    tolerance = opt_int(body, "precedent_deviation_tolerance_bps", 2000, minimum=0)

    for existing in db.bargaining_units.values():
        if existing["local_number"] == local_number:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER", "local_number is already registered.")

    unit = base_record()
    unit.update({
        "name": name,
        "local_number": local_number,
        "contract_effective_date": effective,
        "contract_expiry_date": expiry,
        "step1_response_days": step1,
        "step2_response_days": step2,
        "step3_response_days": step3,
        "appeal_window_days": appeal_days,
        "filing_window_days": filing_days,
        "arbitration_demand_days": arbitration_days,
        "tolling_enabled": tolling,
        "director_authority_cents": director_cents,
        "negotiator_authority_cents": negotiator_cents,
        "precedent_deviation_tolerance_bps": tolerance,
    })
    db.bargaining_units[unit["id"]] = unit
    return ok(ser_unit(unit), 201)


@bp.get("/bargaining-units/<unit_id>")
def read_bargaining_unit(unit_id):
    authenticate(READ_ROLES)
    unit = services.find_unit(unit_id)
    return ok(ser_unit(unit))


# --------------------------------------------------------------------------
# Contract clauses
# --------------------------------------------------------------------------
@bp.post("/bargaining-units/<unit_id>/contract-clauses")
def create_contract_clause(unit_id):
    authenticate([ROLE_DIRECTOR])
    unit = services.find_unit(unit_id)
    body = get_body()

    clause_number = req_string(body, "clause_number")
    title = req_string(body, "title")
    category = req_enum(body, "category", CLAUSE_CATEGORIES)
    is_arbitrable = opt_bool(body, "is_arbitrable", True)
    monetary_cap = opt_int(body, "monetary_cap_cents", None, minimum=0)
    expedited = opt_bool(body, "expedited", False)

    for existing in derive.clauses_of(unit["id"]):
        if existing["clause_number"] == clause_number:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER",
                           "clause_number is already used in this agreement.")

    clause = base_record()
    clause.update({
        "bargaining_unit_id": unit["id"],
        "clause_number": clause_number,
        "title": title,
        "category": category,
        "is_arbitrable": is_arbitrable,
        "monetary_cap_cents": monetary_cap,
        "expedited": expedited,
    })
    db.contract_clauses[clause["id"]] = clause
    return ok(ser_clause(clause), 201)


@bp.get("/bargaining-units/<unit_id>/contract-clauses")
def list_contract_clauses(unit_id):
    authenticate(READ_ROLES)
    unit = services.find_unit(unit_id)
    rows = derive.clauses_of(unit["id"])
    category = qp("category")
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    rows = order_by(rows, "clause_number")
    return paginated(rows, ser_clause)


# --------------------------------------------------------------------------
# People
# --------------------------------------------------------------------------
@bp.post("/employees")
def create_employee():
    authenticate([ROLE_DIRECTOR])
    body = get_body()

    unit_id = req_id(body, "bargaining_unit_id")
    full_name = req_string(body, "full_name")
    employee_number = req_string(body, "employee_number")
    hire_date = req_dt(body, "hire_date")
    seniority_date = req_dt(body, "seniority_date")
    if seniority_date < hire_date:
        bad("seniority_date", "must be at or after hire_date")
    hourly_rate = req_int(body, "hourly_rate_cents", minimum=1)
    classification = req_enum(body, "classification", CLASSIFICATIONS)
    supervisor_id = opt_id(body, "supervisor_id")
    employment_status = opt_enum(body, "employment_status", EMPLOYMENT_STATUSES, "ACTIVE")

    unit = services.find_unit(unit_id)
    if supervisor_id is not None:
        services.find_employee(supervisor_id)

    for existing in db.employees.values():
        if existing["bargaining_unit_id"] == unit["id"] and \
                existing["employee_number"] == employee_number:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER",
                           "employee_number is already used in this bargaining unit.")

    employee = base_record()
    employee.update({
        "bargaining_unit_id": unit["id"],
        "supervisor_id": supervisor_id,
        "full_name": full_name,
        "employee_number": employee_number,
        "hire_date": hire_date,
        "seniority_date": seniority_date,
        "hourly_rate_cents": hourly_rate,
        "classification": classification,
        "employment_status": employment_status,
    })
    db.employees[employee["id"]] = employee
    return ok(ser_employee(employee), 201)


@bp.get("/employees/<employee_id>")
def read_employee(employee_id):
    authenticate(READ_ROLES)
    employee = services.find_employee(employee_id)
    return ok(ser_employee(employee))


@bp.get("/employees")
def list_employees():
    authenticate(READ_ROLES)
    rows = list(db.employees.values())
    unit_id = qp("bargaining_unit_id")
    if unit_id is not None:
        rows = [r for r in rows if r["bargaining_unit_id"] == unit_id]
    supervisor_id = qp("supervisor_id")
    if supervisor_id is not None:
        rows = [r for r in rows if r["supervisor_id"] == supervisor_id]
    classification = qp("classification")
    if classification is not None:
        rows = [r for r in rows if r["classification"] == classification]
    employment_status = qp("employment_status")
    if employment_status is not None:
        rows = [r for r in rows if r["employment_status"] == employment_status]
    rows = order_by(rows, "employee_number")
    return paginated(rows, ser_employee)


@bp.get("/employees/<employee_id>/witness-assignments")
def list_employee_witness_assignments(employee_id):
    authenticate(READ_ROLES)
    employee = services.find_employee(employee_id)
    rows = [w for w in db.witness_assignments.values() if w["employee_id"] == employee["id"]]
    status = qp("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = order_by(rows, "slot_start_at", "created_at")
    return paginated(rows, derive.ser_assignment)


# --------------------------------------------------------------------------
# Precedent library
# --------------------------------------------------------------------------
@bp.post("/precedent-cases")
def create_precedent_case():
    authenticate([ROLE_DIRECTOR])
    body = get_body()

    clause_id = req_id(body, "clause_id")
    citation = req_string(body, "citation")
    decided_on = req_dt(body, "decided_on")
    outcome = req_enum(body, "outcome", PRECEDENT_OUTCOMES)
    monetary_value = req_int(body, "monetary_value_cents", minimum=0)
    binding_scope = req_enum(body, "binding_scope", BINDING_SCOPES)
    arbitrator_name = req_string(body, "arbitrator_name")

    clause = services.find_clause(clause_id)

    for existing in db.precedent_cases.values():
        if existing["citation"] == citation:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER", "citation is already recorded.")

    precedent = base_record(with_version=False)
    precedent.update({
        "clause_id": clause["id"],
        "citation": citation,
        "decided_on": decided_on,
        "outcome": outcome,
        "monetary_value_cents": monetary_value,
        "binding_scope": binding_scope,
        "arbitrator_name": arbitrator_name,
    })
    db.precedent_cases[precedent["id"]] = precedent
    return ok(ser_precedent(precedent), 201)


@bp.get("/precedent-cases/<precedent_id>")
def read_precedent_case(precedent_id):
    authenticate(READ_ROLES)
    precedent = services.find_precedent(precedent_id)
    return ok(ser_precedent(precedent))


@bp.get("/precedent-cases")
def list_precedent_cases():
    authenticate(READ_ROLES)
    rows = list(db.precedent_cases.values())
    clause_id = qp("clause_id")
    if clause_id is not None:
        rows = [r for r in rows if r["clause_id"] == clause_id]
    binding_scope = qp("binding_scope")
    if binding_scope is not None:
        rows = [r for r in rows if r["binding_scope"] == binding_scope]
    outcome = qp("outcome")
    if outcome is not None:
        rows = [r for r in rows if r["outcome"] == outcome]
    rows = order_by(rows, ("decided_on", "desc"), "citation")
    return paginated(rows, ser_precedent)


# --------------------------------------------------------------------------
# Arbitrator roster
# --------------------------------------------------------------------------
@bp.post("/arbitrators")
def create_arbitrator():
    authenticate([ROLE_ADMIN])
    body = get_body()

    full_name = req_string(body, "full_name")
    memberships = req_enum_array(body, "panel_memberships", PANEL_SOURCES)
    per_diem = req_int(body, "per_diem_cents", minimum=1)
    cancellation_fee = req_int(body, "cancellation_fee_cents", minimum=0)
    earliest_available = req_dt(body, "earliest_available_at")
    travel_buffer = opt_int(body, "travel_buffer_hours", 24, minimum=0)
    max_cases = opt_int(body, "max_concurrent_cases", 3, minimum=1)
    is_active = opt_bool(body, "is_active", True)

    arbitrator = base_record()
    arbitrator.update({
        "full_name": full_name,
        "panel_memberships": memberships,
        "per_diem_cents": per_diem,
        "cancellation_fee_cents": cancellation_fee,
        "travel_buffer_hours": travel_buffer,
        "earliest_available_at": earliest_available,
        "max_concurrent_cases": max_cases,
        "is_active": is_active,
        "active_case_count": 0,
    })
    db.arbitrators[arbitrator["id"]] = arbitrator
    return ok(ser_arbitrator(arbitrator), 201)


@bp.get("/arbitrators/<arbitrator_id>")
def read_arbitrator(arbitrator_id):
    authenticate(READ_ROLES)
    arbitrator = services.find_arbitrator(arbitrator_id)
    return ok(ser_arbitrator(arbitrator))


@bp.patch("/arbitrators/<arbitrator_id>")
def patch_arbitrator(arbitrator_id):
    authenticate([ROLE_ADMIN])
    arbitrator = services.find_arbitrator(arbitrator_id)
    body = get_body()

    is_active = opt_bool(body, "is_active", None)
    earliest_available = opt_dt(body, "earliest_available_at", None)
    max_cases = opt_int(body, "max_concurrent_cases", None, minimum=1)
    per_diem = opt_int(body, "per_diem_cents", None, minimum=1)

    if is_active is not None:
        arbitrator["is_active"] = is_active
    if earliest_available is not None:
        arbitrator["earliest_available_at"] = earliest_available
    if max_cases is not None:
        arbitrator["max_concurrent_cases"] = max_cases
    if per_diem is not None:
        arbitrator["per_diem_cents"] = per_diem
    touch(arbitrator)
    return ok(ser_arbitrator(arbitrator))


@bp.get("/arbitrators/<arbitrator_id>/strike-history")
def list_arbitrator_strikes(arbitrator_id):
    authenticate(READ_ROLES)
    arbitrator = services.find_arbitrator(arbitrator_id)
    rows = [s for s in db.panel_strikes.values() if s["arbitrator_id"] == arbitrator["id"]]
    struck_by = qp("struck_by")
    if struck_by is not None:
        rows = [r for r in rows if r["struck_by"] == struck_by]
    rows = order_by(rows, "created_at", "strike_order")
    return paginated(rows, ser_strike)


# --------------------------------------------------------------------------
# Logical clock (PRD 2.4) — mounted outside the /labor-relations prefix
# --------------------------------------------------------------------------
@clock_bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate([ROLE_DIRECTOR])
    body = get_body()
    instant = req_dt(body, "to_iso8601")
    db.clock = instant
    return ok({"current_utc": core.fmt_dt(db.clock)})
