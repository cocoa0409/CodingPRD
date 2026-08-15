"""All API route handlers, grouped by resource.

Validation order per PRD §2.9: auth (1) -> role (2) -> request shape (3) ->
existence (4, left-to-right) -> ownership/SoD (5) -> OCC (6) -> state (7) ->
safety (8) -> overlap/uniqueness/capacity (9) -> rest (10) -> linkage (11) ->
temporal (12) -> season cap (13).
"""
from datetime import timedelta

from flask import Blueprint, request

import db
import services as svc
from errors import (
    ApiError, bad_request, invalid_state, already_terminal,
    ERR_CONTRACT_NOT_FOUND, ERR_AIRCRAFT_NOT_FOUND, ERR_CREW_MEMBER_NOT_FOUND,
    ERR_INCIDENT_NOT_FOUND, ERR_DISPATCH_ORDER_NOT_FOUND, ERR_ASSIGNMENT_NOT_FOUND,
    ERR_INVOICE_NOT_FOUND, ERR_AVAILABILITY_PERIOD_NOT_FOUND,
    ERR_INSPECTION_NOT_FOUND, ERR_RETARDANT_LOAD_NOT_FOUND,
    ERR_FORBIDDEN_OWNERSHIP, ERR_SEGREGATION_OF_DUTIES, ERR_STALE_VERSION,
    ERR_CONTRACT_NOT_ACTIVE, ERR_INVALID_STATE, ERR_ALREADY_TERMINAL,
    ERR_AIRCRAFT_NOT_CARDED, ERR_CREW_NOT_CARDED, ERR_DISPATCH_ALREADY_FILLED,
    ERR_ASSIGNMENT_OVERLAP, ERR_AVAILABILITY_OVERLAP, ERR_INVOICE_PERIOD_OVERLAP,
    ERR_CARDING_EXPIRED, ERR_CREW_ON_FATIGUE_HOLD, ERR_FLIGHT_HOUR_LIMIT_EXCEEDED,
    ERR_CREW_DAY_LIMIT_EXCEEDED, ERR_DUTY_REST_VIOLATION,
    ERR_ACCEPTANCE_WINDOW_EXPIRED, ERR_CONFIRM_WINDOW_EXPIRED,
    ERR_SERVICE_DATE_OUTSIDE_SEASON, ERR_BILLING_PERIOD_NOT_CLOSED,
    ERR_SEASON_FLIGHT_CAP_EXCEEDED, ERR_AIRCRAFT_NOT_ON_CONTRACT,
    ERR_PILOT_NOT_ON_CONTRACT, ERR_MODEL_MISMATCH, ERR_MODEL_NOT_QUALIFIED,
    ERR_TANK_CAPACITY_EXCEEDED,
)
from helpers import (
    body, req_str, opt_str, req_int, opt_int, req_number, req_enum, opt_enum,
    req_date, parse_date, req_datetime, opt_datetime, parse_datetime, fmt_dt,
    fmt_date, str_to_date,
)
from middleware import require_roles, ALL_BUSINESS_ROLES
from response import success_object, success_list

bp = Blueprint("api", __name__)


# ---------------------------------------------------------------------------
# common helpers
# ---------------------------------------------------------------------------
def paginate(items, serializer):
    """limit default 10, min 1, max 100; offset default 0 (PRD §2.3)."""
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        raise bad_request("limit must be an integer")
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise bad_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise bad_request("limit must be between 1 and 100")
    if offset < 0:
        raise bad_request("offset must be >= 0")
    # default sort: created_at ascending (deterministic creation order)
    items = sorted(items, key=lambda e: (e.get("created_at", ""), e.get("_seq", 0)))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializer(e) for e in page], limit, offset, total)


def get_contract_or_404(cid):
    c = db.contracts.get(cid)
    if c is None:
        raise ApiError(ERR_CONTRACT_NOT_FOUND, "contract id does not exist", 404)
    return c


def get_aircraft_or_404(aid):
    a = db.aircraft.get(aid)
    if a is None:
        raise ApiError(ERR_AIRCRAFT_NOT_FOUND, "aircraft id does not exist", 404)
    return a


def get_crew_or_404(mid):
    m = db.crew_members.get(mid)
    if m is None:
        raise ApiError(ERR_CREW_MEMBER_NOT_FOUND, "crew member id does not exist", 404)
    return m


def get_incident_or_404(iid):
    i = db.incidents.get(iid)
    if i is None:
        raise ApiError(ERR_INCIDENT_NOT_FOUND, "incident id does not exist", 404)
    return i


def get_order_or_404(oid):
    o = db.dispatch_orders.get(oid)
    if o is None:
        raise ApiError(ERR_DISPATCH_ORDER_NOT_FOUND, "dispatch order id does not exist", 404)
    return o


def get_assignment_or_404(aid):
    a = db.assignments.get(aid)
    if a is None:
        raise ApiError(ERR_ASSIGNMENT_NOT_FOUND, "assignment id does not exist", 404)
    return a


def get_invoice_or_404(iid):
    i = db.invoices.get(iid)
    if i is None:
        raise ApiError(ERR_INVOICE_NOT_FOUND, "invoice id does not exist", 404)
    return i


def get_period_or_404(pid):
    p = db.availability_periods.get(pid)
    if p is None:
        raise ApiError(ERR_AVAILABILITY_PERIOD_NOT_FOUND, "availability period id does not exist", 404)
    return p


def get_inspection_or_404(iid):
    i = db.carding_inspections.get(iid)
    if i is None:
        raise ApiError(ERR_INSPECTION_NOT_FOUND, "carding inspection id does not exist", 404)
    return i


def get_load_or_404(lid):
    l = db.retardant_loads.get(lid)
    if l is None:
        raise ApiError(ERR_RETARDANT_LOAD_NOT_FOUND, "retardant load id does not exist", 404)
    return l


# ===========================================================================
# Contracts
# ===========================================================================
@bp.post("/contracts")
def create_contract():
    require_roles(["CarrierOps"])
    data = body()
    contract_number = req_str(data, "contract_number")
    agency = req_enum(data, "agency", {"USFS", "CAL_FIRE"})
    contract_type = req_enum(data, "contract_type", {"EXCLUSIVE_USE", "CALL_WHEN_NEEDED"})
    daily_availability_rate_cents = req_int(data, "daily_availability_rate_cents")
    if daily_availability_rate_cents <= 0:
        raise bad_request("daily_availability_rate_cents must be > 0")
    flight_hour_rate_cents = req_int(data, "flight_hour_rate_cents")
    if flight_hour_rate_cents <= 0:
        raise bad_request("flight_hour_rate_cents must be > 0")
    season_start = req_date(data, "season_start_date")
    season_end = req_date(data, "season_end_date")
    if season_end <= season_start:
        raise bad_request("season_end_date must be strictly after season_start_date")
    min_daily = opt_int(data, "min_daily_available_minutes", svc.DEFAULT_MIN_DAILY_MINUTES)
    if min_daily is None or min_daily <= 0:
        raise bad_request("min_daily_available_minutes must be > 0")
    cap = req_int(data, "season_flight_hour_cap_tenths")
    if cap <= 0:
        raise bad_request("season_flight_hour_cap_tenths must be > 0")
    accept_window = req_int(data, "acceptance_window_minutes")
    if accept_window <= 0:
        raise bad_request("acceptance_window_minutes must be > 0")

    now = db.iso_now_ms()
    c = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "contract_number": contract_number,
        "agency": agency,
        "contract_type": contract_type,
        "daily_availability_rate_cents": daily_availability_rate_cents,
        "flight_hour_rate_cents": flight_hour_rate_cents,
        "season_start_date": season_start.isoformat(),
        "season_end_date": season_end.isoformat(),
        "min_daily_available_minutes": min_daily,
        "season_flight_hour_cap_tenths": cap,
        "acceptance_window_minutes": accept_window,
        "status": "DRAFT",
        "season_billed_cents": 0,
        "season_flight_hours_tenths": 0,
    }
    db.stamp_new(c)
    db.contracts[c["id"]] = c
    return success_object(svc.ser_contract(c), 201)


@bp.get("/contracts")
def list_contracts():
    require_roles(ALL_BUSINESS_ROLES)
    items = list(db.contracts.values())
    status = request.args.get("status")
    ctype = request.args.get("contract_type")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if ctype is not None:
        items = [c for c in items if c["contract_type"] == ctype]
    return paginate(items, svc.ser_contract)


@bp.get("/contracts/<cid>")
def get_contract(cid):
    require_roles(ALL_BUSINESS_ROLES)
    c = get_contract_or_404(cid)
    return success_object(svc.ser_contract(c))


def _contract_transition(cid, allowed_from, target):
    require_roles(["CarrierOps"])
    c = get_contract_or_404(cid)
    if c["status"] in svc.CONTRACT_TERMINAL:
        raise already_terminal("contract is CLOSED (terminal)")
    if c["status"] not in allowed_from:
        raise invalid_state(f"cannot transition contract from {c['status']} to {target}")
    c["status"] = target
    svc.touch(c)
    return success_object(svc.ser_contract(c))


@bp.post("/contracts/<cid>/activate")
def activate_contract(cid):
    return _contract_transition(cid, {"DRAFT"}, "ACTIVE")


@bp.post("/contracts/<cid>/suspend")
def suspend_contract(cid):
    return _contract_transition(cid, {"ACTIVE"}, "SUSPENDED")


@bp.post("/contracts/<cid>/resume")
def resume_contract(cid):
    return _contract_transition(cid, {"SUSPENDED"}, "ACTIVE")


@bp.post("/contracts/<cid>/close")
def close_contract(cid):
    require_roles(["CarrierOps"])
    c = get_contract_or_404(cid)
    if c["status"] in svc.CONTRACT_TERMINAL:
        raise already_terminal("contract is CLOSED (terminal)")
    if c["status"] not in ("ACTIVE", "SUSPENDED"):
        raise invalid_state(f"cannot close contract from {c['status']}")
    for o in db.dispatch_orders.values():
        if o["contract_id"] == c["id"] and o["status"] in svc.OPEN_ORDER_STATUSES:
            raise invalid_state("contract has open dispatch orders")
    c["status"] = "CLOSED"
    svc.touch(c)
    return success_object(svc.ser_contract(c))


@bp.get("/contracts/<cid>/availability-periods")
def list_contract_periods(cid):
    require_roles(ALL_BUSINESS_ROLES)
    get_contract_or_404(cid)
    items = [p for p in db.availability_periods.values() if p["contract_id"] == cid]
    sd = request.args.get("service_date")
    st = request.args.get("status")
    if sd is not None:
        items = [p for p in items if p["service_date"] == sd]
    if st is not None:
        items = [p for p in items if p["status"] == st]
    return paginate(items, svc.ser_period)


@bp.get("/contracts/<cid>/invoices")
def list_contract_invoices(cid):
    require_roles(ALL_BUSINESS_ROLES)
    get_contract_or_404(cid)
    items = [i for i in db.invoices.values() if i["contract_id"] == cid]
    st = request.args.get("status")
    if st is not None:
        items = [i for i in items if i["status"] == st]
    return paginate(items, svc.ser_invoice)


@bp.get("/contracts/<cid>/agency-records")
def list_contract_agency_records(cid):
    require_roles(ALL_BUSINESS_ROLES)
    get_contract_or_404(cid)
    items = [r for r in db.agency_records.values() if r["contract_id"] == cid]
    rd = request.args.get("record_date")
    if rd is not None:
        items = [r for r in items if r["record_date"] == rd]
    return paginate(items, svc.ser_agency_record)


# ===========================================================================
# Aircraft
# ===========================================================================
@bp.post("/aircraft")
def create_aircraft():
    require_roles(["CarrierOps"])
    data = body()
    tail_number = req_str(data, "tail_number")
    model = req_str(data, "model")
    tank = req_int(data, "tank_capacity_gallons")
    if tank <= 0:
        raise bad_request("tank_capacity_gallons must be > 0")
    contract_id = req_str(data, "contract_id")
    get_contract_or_404(contract_id)
    now = db.iso_now_ms()
    a = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "tail_number": tail_number,
        "model": model,
        "tank_capacity_gallons": tank,
        "contract_id": contract_id,
        "carding_status": "UNCARDED",
        "carded_until": None,
    }
    db.stamp_new(a)
    db.aircraft[a["id"]] = a
    return success_object(svc.ser_aircraft(a), 201)


@bp.get("/aircraft")
def list_aircraft():
    require_roles(ALL_BUSINESS_ROLES)
    items = list(db.aircraft.values())
    cid = request.args.get("contract_id")
    cs = request.args.get("carding_status")
    if cid is not None:
        items = [a for a in items if a["contract_id"] == cid]
    if cs is not None:
        items = [a for a in items if a["carding_status"] == cs]
    return paginate(items, svc.ser_aircraft)


@bp.get("/aircraft/<aid>")
def get_aircraft(aid):
    require_roles(ALL_BUSINESS_ROLES)
    return success_object(svc.ser_aircraft(get_aircraft_or_404(aid)))


@bp.post("/aircraft/<aid>/decard")
def decard_aircraft(aid):
    require_roles(["CarrierOps"])
    a = get_aircraft_or_404(aid)
    if a["carding_status"] == "DECARDED":
        raise already_terminal("aircraft is DECARDED (terminal)")
    if a["carding_status"] not in ("CARDED", "UNCARDED"):
        raise invalid_state(f"cannot decard aircraft from {a['carding_status']}")
    if a["carding_status"] == "CARDED":
        for asg in db.assignments.values():
            if asg["aircraft_id"] == a["id"] and asg["status"] in svc.FILLED_STATUSES:
                raise invalid_state("aircraft has non-terminal assignments")
    a["carding_status"] = "DECARDED"
    a["carded_until"] = None
    svc.touch(a)
    return success_object(svc.ser_aircraft(a))


@bp.get("/aircraft/<aid>/carding-inspections")
def list_aircraft_inspections(aid):
    require_roles(ALL_BUSINESS_ROLES)
    get_aircraft_or_404(aid)
    items = [i for i in db.carding_inspections.values() if i["subject_aircraft_id"] == aid]
    r = request.args.get("result")
    if r is not None:
        items = [i for i in items if i["result"] == r]
    return paginate(items, svc.ser_inspection)


# ===========================================================================
# Crew members
# ===========================================================================
@bp.post("/crew-members")
def create_crew_member():
    require_roles(["CarrierOps"])
    data = body()
    full_name = req_str(data, "full_name")
    crew_role = req_enum(data, "crew_role", {"PIC", "SIC"})
    contract_id = req_str(data, "contract_id")
    get_contract_or_404(contract_id)
    qam = data.get("qualified_aircraft_models")
    if qam is None:
        raise bad_request("missing required field: qualified_aircraft_models")
    if not isinstance(qam, list) or any(not isinstance(x, str) for x in qam):
        raise bad_request("qualified_aircraft_models must be an array of strings")
    now = db.iso_now_ms()
    m = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "full_name": full_name,
        "crew_role": crew_role,
        "contract_id": contract_id,
        "qualified_aircraft_models": list(qam),
        "carding_status": "UNCARDED",
        "carded_until": None,
        "duty_status": "AVAILABLE",
    }
    db.stamp_new(m)
    db.crew_members[m["id"]] = m
    return success_object(svc.ser_crew(m), 201)


@bp.get("/crew-members")
def list_crew_members():
    require_roles(ALL_BUSINESS_ROLES)
    items = list(db.crew_members.values())
    cid = request.args.get("contract_id")
    ds = request.args.get("duty_status")
    cs = request.args.get("carding_status")
    if cid is not None:
        items = [m for m in items if m["contract_id"] == cid]
    if ds is not None:
        items = [m for m in items if m["duty_status"] == ds]
    if cs is not None:
        items = [m for m in items if m["carding_status"] == cs]
    return paginate(items, svc.ser_crew)


@bp.get("/crew-members/<mid>")
def get_crew_member(mid):
    require_roles(ALL_BUSINESS_ROLES)
    return success_object(svc.ser_crew(get_crew_or_404(mid)))


@bp.get("/crew-members/<mid>/duty-days")
def list_crew_duty_days(mid):
    require_roles(ALL_BUSINESS_ROLES)
    get_crew_or_404(mid)
    items = [d for d in db.crew_duty_days.values() if d["crew_member_id"] == mid]
    dd = request.args.get("duty_date")
    if dd is not None:
        items = [d for d in items if d["duty_date"] == dd]
    return paginate(items, svc.ser_duty_day)


@bp.get("/crew-members/<mid>/carding-inspections")
def list_crew_inspections(mid):
    require_roles(ALL_BUSINESS_ROLES)
    get_crew_or_404(mid)
    items = [i for i in db.carding_inspections.values() if i["subject_crew_member_id"] == mid]
    r = request.args.get("result")
    if r is not None:
        items = [i for i in items if i["result"] == r]
    return paginate(items, svc.ser_inspection)


@bp.get("/crew-members/<mid>/flight-logs")
def list_crew_flight_logs(mid):
    require_roles(ALL_BUSINESS_ROLES)
    get_crew_or_404(mid)
    items = [f for f in db.flight_logs.values() if f["pilot_id"] == mid]
    ld = request.args.get("logged_date")
    if ld is not None:
        items = [f for f in items if f["logged_date"] == ld]
    return paginate(items, svc.ser_flight_log)


@bp.post("/crew-members/<mid>/rest-release")
def rest_release(mid):
    require_roles(["CarrierOps"])
    m = get_crew_or_404(mid)
    if m["duty_status"] != "FATIGUE_HOLD":
        raise invalid_state("crew member is not on FATIGUE_HOLD")
    days = [d for d in db.crew_duty_days.values() if d["crew_member_id"] == mid]
    if days:
        latest = max(days, key=lambda d: d["duty_date"])
        clock_date = db.clock_now().date()
        if not (str_to_date(latest["duty_date"]) < clock_date):
            raise invalid_state("latest duty day is not strictly before the current clock date")
    m["duty_status"] = "AVAILABLE"
    svc.touch(m)
    return success_object(svc.ser_crew(m))


# ===========================================================================
# Carding inspections
# ===========================================================================
@bp.post("/carding-inspections")
def create_inspection():
    require_roles(["CardingInspector"])
    data = body()
    subj_aircraft = data.get("subject_aircraft_id")
    subj_crew = data.get("subject_crew_member_id")
    if subj_aircraft is not None and not isinstance(subj_aircraft, str):
        raise bad_request("subject_aircraft_id must be a string")
    if subj_crew is not None and not isinstance(subj_crew, str):
        raise bad_request("subject_crew_member_id must be a string")
    if (subj_aircraft is None) == (subj_crew is None):
        raise bad_request("exactly one of subject_aircraft_id / subject_crew_member_id must be set")
    scheduled_for = req_datetime(data, "scheduled_for")
    valid_days = opt_int(data, "valid_days", 365)
    if valid_days is None or valid_days <= 0:
        raise bad_request("valid_days must be > 0")
    notes = opt_str(data, "notes", None)
    if subj_aircraft is not None:
        get_aircraft_or_404(subj_aircraft)
    else:
        get_crew_or_404(subj_crew)
    now = db.iso_now_ms()
    i = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "subject_aircraft_id": subj_aircraft,
        "subject_crew_member_id": subj_crew,
        "scheduled_for": scheduled_for,
        "valid_days": valid_days,
        "status": "SCHEDULED",
        "result": "PENDING",
        "completed_at": None,
        "notes": notes,
    }
    db.stamp_new(i)
    db.carding_inspections[i["id"]] = i
    return success_object(svc.ser_inspection(i), 201)


@bp.post("/carding-inspections/<iid>/complete")
def complete_inspection(iid):
    require_roles(["CardingInspector"])
    data = body()
    result = req_enum(data, "result", {"PASSED", "FAILED"})
    completed_at = req_datetime(data, "completed_at")
    insp = get_inspection_or_404(iid)
    if insp["status"] != "SCHEDULED":
        raise invalid_state("inspection is not SCHEDULED")
    if completed_at < insp["scheduled_for"]:
        raise invalid_state("completed_at must be >= scheduled_for")

    insp["result"] = result
    insp["completed_at"] = completed_at
    insp["status"] = "COMPLETED"

    # subject transition
    if insp["subject_aircraft_id"] is not None:
        subject = db.aircraft[insp["subject_aircraft_id"]]
        is_aircraft = True
    else:
        subject = db.crew_members[insp["subject_crew_member_id"]]
        is_aircraft = False

    if result == "PASSED":
        if subject["carding_status"] in ("UNCARDED", "SUSPENDED"):
            subject["carding_status"] = "CARDED"
            subject["carded_until"] = (
                completed_at.date() + timedelta(days=insp["valid_days"])
            ).isoformat()
            svc.touch(subject)
    else:  # FAILED
        if subject["carding_status"] == "CARDED":
            subject["carding_status"] = "SUSPENDED"
            subject["carded_until"] = None
            svc.touch(subject)
            if is_aircraft:
                svc.fire_aircraft_failed_inspection_cascade(subject, completed_at)
        elif subject["carding_status"] == "UNCARDED":
            # PRD: "On FAILED, a CARDED subject drops to SUSPENDED" — an
            # UNCARDED subject has no card to suspend.
            pass
    svc.touch(insp)
    return success_object(svc.ser_inspection(insp))


@bp.post("/carding-inspections/<iid>/reschedule")
def reschedule_inspection(iid):
    require_roles(["CardingInspector"])
    data = body()
    scheduled_for = req_datetime(data, "scheduled_for")
    insp = get_inspection_or_404(iid)
    if insp["status"] != "COMPLETED" or insp["result"] != "FAILED":
        raise invalid_state("only a COMPLETED inspection with result FAILED may be rescheduled")
    insp["status"] = "SCHEDULED"
    insp["result"] = "PENDING"
    insp["completed_at"] = None
    insp["scheduled_for"] = scheduled_for
    svc.touch(insp)
    return success_object(svc.ser_inspection(insp))


# ===========================================================================
# Availability periods
# ===========================================================================
@bp.post("/contracts/<cid>/availability-periods")
def create_availability_period(cid):
    require_roles(["CarrierOps"])
    data = body()
    aircraft_id = req_str(data, "aircraft_id")
    service_date = req_date(data, "service_date")
    available_start = req_datetime(data, "available_start")
    available_end = req_datetime(data, "available_end")
    if available_end <= available_start:
        raise bad_request("available_end must be strictly after available_start")

    contract = get_contract_or_404(cid)
    aircraft = get_aircraft_or_404(aircraft_id)

    # state
    if contract["status"] in svc.CONTRACT_TERMINAL:
        raise already_terminal("contract is CLOSED (terminal)")
    if contract["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACT_NOT_ACTIVE, "contract is not ACTIVE", 409)

    # uniqueness: at most one period per (aircraft_id, service_date) ever
    for p in db.availability_periods.values():
        if p["aircraft_id"] == aircraft_id and p["service_date"] == service_date.isoformat():
            raise ApiError(ERR_AVAILABILITY_OVERLAP, "an AvailabilityPeriod already exists for (aircraft_id, service_date)", 409)

    # temporal: service_date inside season
    if not (str_to_date(contract["season_start_date"]) <= service_date <= str_to_date(contract["season_end_date"])):
        raise ApiError(ERR_SERVICE_DATE_OUTSIDE_SEASON, "service_date outside contract season", 422)

    minutes = int((available_end - available_start).total_seconds() // 60)
    status = "CONFIRMED" if contract["contract_type"] == "EXCLUSIVE_USE" else "OFFERED"
    now = db.iso_now_ms()
    p = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "contract_id": cid,
        "aircraft_id": aircraft_id,
        "service_date": service_date.isoformat(),
        "available_start": available_start,
        "available_end": available_end,
        "status": status,
        "excuse_reason": None,
        "available_minutes": minutes,
        "availability_charge_cents": 0,
    }
    db.stamp_new(p)
    db.availability_periods[p["id"]] = p
    p["availability_charge_cents"] = svc.compute_availability_charge(p, contract)
    svc.rederive_covering_draft_invoices(cid, p["service_date"])
    return success_object(svc.ser_period(p), 201)


@bp.get("/availability-periods")
def list_periods():
    require_roles(ALL_BUSINESS_ROLES)
    items = list(db.availability_periods.values())
    aid = request.args.get("aircraft_id")
    cid = request.args.get("contract_id")
    sd = request.args.get("service_date")
    st = request.args.get("status")
    if aid is not None:
        items = [p for p in items if p["aircraft_id"] == aid]
    if cid is not None:
        items = [p for p in items if p["contract_id"] == cid]
    if sd is not None:
        items = [p for p in items if p["service_date"] == sd]
    if st is not None:
        items = [p for p in items if p["status"] == st]
    return paginate(items, svc.ser_period)


@bp.get("/availability-periods/<pid>")
def get_period(pid):
    require_roles(ALL_BUSINESS_ROLES)
    return success_object(svc.ser_period(get_period_or_404(pid)))


@bp.post("/availability-periods/<pid>/confirm")
def confirm_period(pid):
    require_roles(["AgencyDispatcher"])
    p = get_period_or_404(pid)
    if p["status"] in svc.PERIOD_TERMINAL:
        raise already_terminal(f"availability period is {p['status']} (terminal)")
    if p["status"] != "OFFERED":
        raise invalid_state("only an OFFERED period may be confirmed")
    if db.clock_now().date() > str_to_date(p["service_date"]):
        raise ApiError(ERR_CONFIRM_WINDOW_EXPIRED, "confirm after the service date has passed", 422)
    p["status"] = "CONFIRMED"
    contract = db.contracts[p["contract_id"]]
    p["availability_charge_cents"] = svc.compute_availability_charge(p, contract)
    svc.touch(p)
    svc.rederive_covering_draft_invoices(p["contract_id"], p["service_date"])
    return success_object(svc.ser_period(p))


@bp.post("/availability-periods/<pid>/excuse")
def excuse_period(pid):
    require_roles(["CarrierOps"])
    data = body()
    reason = req_enum(data, "excuse_reason", {"MAINTENANCE", "CARDING", "WEATHER", "AGENCY_RELEASE"})
    p = get_period_or_404(pid)
    if p["status"] in svc.PERIOD_TERMINAL:
        raise already_terminal(f"availability period is {p['status']} (terminal)")
    if p["status"] not in ("OFFERED", "CONFIRMED"):
        raise invalid_state("only an OFFERED or CONFIRMED period may be excused")
    was_confirmed = p["status"] == "CONFIRMED"
    p["status"] = "EXCUSED"
    p["excuse_reason"] = reason
    p["availability_charge_cents"] = 0
    svc.touch(p)
    if was_confirmed:
        svc.rederive_covering_draft_invoices(p["contract_id"], p["service_date"])
    return success_object(svc.ser_period(p))


# ===========================================================================
# Incidents
# ===========================================================================
@bp.post("/incidents")
def create_incident():
    require_roles(["AgencyDispatcher"])
    data = body()
    incident_number = req_str(data, "incident_number")
    name = req_str(data, "name")
    location = req_str(data, "location")
    agency = req_enum(data, "agency", {"USFS", "CAL_FIRE"})
    priority = req_enum(data, "priority", {"INITIAL_ATTACK", "EXTENDED_ATTACK"})
    now = db.iso_now_ms()
    i = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "incident_number": incident_number,
        "name": name,
        "location": location,
        "agency": agency,
        "priority": priority,
        "status": "REPORTED",
    }
    db.stamp_new(i)
    db.incidents[i["id"]] = i
    return success_object(svc.ser_incident(i), 201)


@bp.get("/incidents")
def list_incidents():
    require_roles(ALL_BUSINESS_ROLES)
    items = list(db.incidents.values())
    st = request.args.get("status")
    ag = request.args.get("agency")
    if st is not None:
        items = [i for i in items if i["status"] == st]
    if ag is not None:
        items = [i for i in items if i["agency"] == ag]
    return paginate(items, svc.ser_incident)


@bp.get("/incidents/<iid>")
def get_incident(iid):
    require_roles(ALL_BUSINESS_ROLES)
    return success_object(svc.ser_incident(get_incident_or_404(iid)))


_INCIDENT_NEXT = {"REPORTED": "ACTIVE", "ACTIVE": "CONTAINED", "CONTAINED": "CLOSED"}


@bp.post("/incidents/<iid>/advance")
def advance_incident(iid):
    require_roles(["AgencyDispatcher"])
    data = body()
    to_status = req_enum(data, "to_status", {"ACTIVE", "CONTAINED", "CLOSED"})
    inc = get_incident_or_404(iid)
    if inc["status"] in svc.INCIDENT_TERMINAL:
        raise already_terminal("incident is CLOSED (terminal)")
    if _INCIDENT_NEXT.get(inc["status"]) != to_status:
        raise invalid_state(f"cannot advance incident from {inc['status']} to {to_status}")
    inc["status"] = to_status
    svc.touch(inc)
    return success_object(svc.ser_incident(inc))


# ===========================================================================
# Dispatch orders
# ===========================================================================
@bp.post("/dispatch-orders")
def create_dispatch_order():
    require_roles(["AgencyDispatcher"])
    data = body()
    order_number = req_str(data, "order_number")
    contract_id = req_str(data, "contract_id")
    incident_id = req_str(data, "incident_id")
    aircraft_quantity = req_int(data, "aircraft_quantity")
    if aircraft_quantity <= 0:
        raise bad_request("aircraft_quantity must be > 0")
    required_model = opt_str(data, "required_model", None)

    contract = get_contract_or_404(contract_id)
    incident = get_incident_or_404(incident_id)

    if contract["status"] in svc.CONTRACT_TERMINAL:
        raise already_terminal("contract is CLOSED (terminal)")
    if contract["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACT_NOT_ACTIVE, "contract is not ACTIVE", 409)

    # season cap gate (priority 13)
    if contract["season_flight_hours_tenths"] >= contract["season_flight_hour_cap_tenths"]:
        raise ApiError(ERR_SEASON_FLIGHT_CAP_EXCEEDED, "season flight-hour cap reached", 422)

    placed_at = db.clock_now()
    accept_deadline = placed_at + timedelta(minutes=contract["acceptance_window_minutes"])
    now = db.iso_now_ms()
    o = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "order_number": order_number,
        "contract_id": contract_id,
        "incident_id": incident_id,
        "aircraft_quantity": aircraft_quantity,
        "required_model": required_model,
        "placed_at": placed_at,
        "accept_deadline": accept_deadline,
        "status": "PLACED",
        "filled_count": 0,
        "decline_reason": None,
    }
    db.stamp_new(o)
    db.dispatch_orders[o["id"]] = o
    return success_object(svc.ser_order(o), 201)


@bp.get("/dispatch-orders")
def list_orders():
    require_roles(ALL_BUSINESS_ROLES)
    items = list(db.dispatch_orders.values())
    cid = request.args.get("contract_id")
    iid = request.args.get("incident_id")
    st = request.args.get("status")
    if cid is not None:
        items = [o for o in items if o["contract_id"] == cid]
    if iid is not None:
        items = [o for o in items if o["incident_id"] == iid]
    if st is not None:
        items = [o for o in items if o["status"] == st]
    return paginate(items, svc.ser_order)


@bp.get("/dispatch-orders/<oid>")
def get_order(oid):
    require_roles(ALL_BUSINESS_ROLES)
    return success_object(svc.ser_order(get_order_or_404(oid)))


@bp.post("/dispatch-orders/<oid>/accept")
def accept_order(oid):
    require_roles(["CarrierOps"])
    o = get_order_or_404(oid)
    if o["status"] in svc.ORDER_TERMINAL:
        raise already_terminal(f"dispatch order is {o['status']} (terminal)")
    if o["status"] != "PLACED":
        raise invalid_state("only a PLACED order may be accepted")
    contract = db.contracts[o["contract_id"]]
    if contract["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACT_NOT_ACTIVE, "contract is not ACTIVE", 409)
    if db.clock_now() > o["accept_deadline"]:
        raise ApiError(ERR_ACCEPTANCE_WINDOW_EXPIRED, "accept after accept_deadline", 422)
    o["status"] = "ACCEPTED"
    svc.touch(o)
    return success_object(svc.ser_order(o))


@bp.post("/dispatch-orders/<oid>/decline")
def decline_order(oid):
    require_roles(["CarrierOps"])
    data = body()
    decline_reason = req_str(data, "decline_reason")
    o = get_order_or_404(oid)
    if o["status"] in svc.ORDER_TERMINAL:
        raise already_terminal(f"dispatch order is {o['status']} (terminal)")
    if o["status"] != "PLACED":
        raise invalid_state("only a PLACED order may be declined")
    o["status"] = "DECLINED"
    o["decline_reason"] = decline_reason
    svc.touch(o)
    return success_object(svc.ser_order(o))


@bp.post("/dispatch-orders/<oid>/cancel")
def cancel_order(oid):
    require_roles(["AgencyDispatcher"])
    o = get_order_or_404(oid)
    if o["status"] in svc.ORDER_TERMINAL:
        raise already_terminal(f"dispatch order is {o['status']} (terminal)")
    if o["status"] == "PLACED":
        pass
    elif o["status"] == "ACCEPTED" and o["filled_count"] == 0:
        pass
    else:
        raise invalid_state("only a PLACED order, or an ACCEPTED order with filled_count == 0, may be cancelled")
    o["status"] = "CANCELLED"
    svc.touch(o)
    return success_object(svc.ser_order(o))


@bp.get("/dispatch-orders/<oid>/assignments")
def list_order_assignments(oid):
    require_roles(ALL_BUSINESS_ROLES)
    get_order_or_404(oid)
    items = [a for a in db.assignments.values() if a["dispatch_order_id"] == oid]
    st = request.args.get("status")
    if st is not None:
        items = [a for a in items if a["status"] == st]
    return paginate(items, svc.ser_assignment)


# ===========================================================================
# Assignments
# ===========================================================================
@bp.post("/dispatch-orders/<oid>/assignments")
def create_assignment(oid):
    require_roles(["CarrierOps"])
    data = body()
    aircraft_id = req_str(data, "aircraft_id")
    pilot_id = req_str(data, "pilot_id")
    planned_start = req_datetime(data, "planned_start")
    planned_end = req_datetime(data, "planned_end")
    if planned_end <= planned_start:
        raise bad_request("planned_end must be strictly after planned_start")
    expected_version = data.get("expected_dispatch_order_version")
    if expected_version is not None and (isinstance(expected_version, bool) or not isinstance(expected_version, int)):
        raise bad_request("expected_dispatch_order_version must be an integer")

    order = get_order_or_404(oid)
    aircraft = get_aircraft_or_404(aircraft_id)
    pilot = get_crew_or_404(pilot_id)

    # (6) OCC
    if expected_version is not None and expected_version != order["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_dispatch_order_version is stale", 412)

    # (7) state gates
    if order["status"] in svc.ORDER_TERMINAL:
        raise already_terminal(f"dispatch order is {order['status']} (terminal)")
    if order["filled_count"] >= order["aircraft_quantity"]:
        raise ApiError(ERR_DISPATCH_ALREADY_FILLED, "order is already FILLED", 409)
    if order["status"] not in ("ACCEPTED", "PARTIALLY_FILLED"):
        raise invalid_state("order is not accepting assignments")
    if aircraft["carding_status"] != "CARDED":
        raise ApiError(ERR_AIRCRAFT_NOT_CARDED, "aircraft is not CARDED", 409)
    if pilot["carding_status"] != "CARDED":
        raise ApiError(ERR_CREW_NOT_CARDED, "pilot is not CARDED", 409)

    # (8) safety gates
    if pilot["duty_status"] == "FATIGUE_HOLD":
        raise ApiError(ERR_CREW_ON_FATIGUE_HOLD, "pilot is on FATIGUE_HOLD", 422)

    duty_date_str = planned_start.date().isoformat()
    dd = svc.get_duty_day(pilot_id, duty_date_str)
    flown = dd["flown_tenths"] if dd is not None else sum(
        fl["flight_hours_tenths"]
        for fl in db.flight_logs.values()
        if fl["pilot_id"] == pilot_id and fl["logged_date"] == duty_date_str
    )
    projected = flown
    for a in db.assignments.values():
        if (
            a["pilot_id"] == pilot_id
            and a["status"] == "ASSIGNED"
            and a["planned_start"].date().isoformat() == duty_date_str
        ):
            projected += svc.planned_tenths(a)
    candidate = {
        "planned_start": planned_start,
        "planned_end": planned_end,
    }
    projected += svc.planned_tenths(candidate)
    if projected > svc.DAILY_FLIGHT_LIMIT_TENTHS:
        raise ApiError(ERR_FLIGHT_HOUR_LIMIT_EXCEEDED, "projected_tenths including candidate > 80", 422)

    duty_start = dd["duty_start"] if dd is not None else None
    if duty_start is None:
        duty_start = planned_start
    span_minutes = (planned_end - duty_start).total_seconds() / 60
    if span_minutes > svc.CREW_DAY_LIMIT_MINUTES:
        raise ApiError(ERR_CREW_DAY_LIMIT_EXCEEDED, "planned_end - duty_start > 840 minutes", 422)

    # (9) overlap gate (aircraft, half-open, non-terminal)
    for a in db.assignments.values():
        if a["aircraft_id"] != aircraft_id or a["status"] in svc.ASSIGNMENT_TERMINAL:
            continue
        if planned_start < a["planned_end"] and a["planned_start"] < planned_end:
            raise ApiError(ERR_ASSIGNMENT_OVERLAP, "aircraft planned window overlaps another non-terminal assignment", 409)

    # (10) rest buffer (pilot, 60 minutes both directions)
    buffer = timedelta(minutes=svc.REST_BUFFER_MINUTES)
    for a in db.assignments.values():
        if a["pilot_id"] != pilot_id or a["status"] in svc.ASSIGNMENT_TERMINAL:
            continue
        if not (a["planned_end"] <= planned_start - buffer or a["planned_start"] >= planned_end + buffer):
            raise ApiError(ERR_DUTY_REST_VIOLATION, "pilot rest buffer violated", 422)

    # (11) linkage and qualification
    if aircraft["contract_id"] != order["contract_id"]:
        raise ApiError(ERR_AIRCRAFT_NOT_ON_CONTRACT, "aircraft not on the order's contract", 422)
    if pilot["contract_id"] != order["contract_id"]:
        raise ApiError(ERR_PILOT_NOT_ON_CONTRACT, "pilot not on the order's contract", 422)
    if order["required_model"] is not None and order["required_model"] != aircraft["model"]:
        raise ApiError(ERR_MODEL_MISMATCH, "aircraft model does not match required_model", 422)
    if aircraft["model"] not in pilot["qualified_aircraft_models"]:
        raise ApiError(ERR_MODEL_NOT_QUALIFIED, "pilot not qualified on aircraft model", 422)

    # create
    assigned_at = db.clock_now()
    now = db.iso_now_ms()
    a = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "dispatch_order_id": oid,
        "aircraft_id": aircraft_id,
        "pilot_id": pilot_id,
        "planned_start": planned_start,
        "planned_end": planned_end,
        "status": "ASSIGNED",
        "assigned_at": fmt_dt(assigned_at),
        "launched_at": None,
        "arrived_at": None,
        "released_at": None,
        "demobilized_at": None,
        "release_reason": None,
        "reload_turn_avg_minutes": None,
        "reload_sla_breach": False,
    }
    db.stamp_new(a)
    db.assignments[a["id"]] = a

    # duty day auto-create + recompute
    if dd is None:
        dd = svc.create_duty_day(pilot_id, duty_date_str, planned_start)
    svc.recompute_duty_day(dd)

    # fill band bubble-up
    svc.recompute_order_fill(order)
    svc.touch(order)

    return success_object(svc.ser_assignment(a), 201)


@bp.get("/assignments")
def list_assignments():
    require_roles(ALL_BUSINESS_ROLES)
    items = list(db.assignments.values())
    aid = request.args.get("aircraft_id")
    pid = request.args.get("pilot_id")
    oid = request.args.get("dispatch_order_id")
    st = request.args.get("status")
    if aid is not None:
        items = [a for a in items if a["aircraft_id"] == aid]
    if pid is not None:
        items = [a for a in items if a["pilot_id"] == pid]
    if oid is not None:
        items = [a for a in items if a["dispatch_order_id"] == oid]
    if st is not None:
        items = [a for a in items if a["status"] == st]
    return paginate(items, svc.ser_assignment)


@bp.get("/assignments/<aid>")
def get_assignment(aid):
    require_roles(ALL_BUSINESS_ROLES)
    return success_object(svc.ser_assignment(get_assignment_or_404(aid)))


def _pilot_ownership_check(user_id, role, assignment):
    if role == "Pilot" and user_id != assignment["pilot_id"]:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Pilot X-User-ID does not equal assignment.pilot_id", 403)


@bp.post("/assignments/<aid>/launch")
def launch_assignment(aid):
    user_id, role = require_roles(["CarrierOps", "Pilot"])
    a = get_assignment_or_404(aid)
    _pilot_ownership_check(user_id, role, a)
    if a["status"] in svc.ASSIGNMENT_TERMINAL:
        raise already_terminal("assignment is DEMOBILIZED (terminal)")
    if a["status"] != "ASSIGNED":
        raise invalid_state("only an ASSIGNED assignment may launch")
    aircraft = db.aircraft[a["aircraft_id"]]
    if aircraft["carding_status"] != "CARDED":
        raise ApiError(ERR_AIRCRAFT_NOT_CARDED, "aircraft is not CARDED", 409)
    clock_date = db.clock_now().date()
    if aircraft["carded_until"] is None or str_to_date(aircraft["carded_until"]) < clock_date:
        raise ApiError(ERR_CARDING_EXPIRED, "aircraft card expired", 422)
    pilot = db.crew_members[a["pilot_id"]]
    if pilot["duty_status"] == "FATIGUE_HOLD":
        raise ApiError(ERR_CREW_ON_FATIGUE_HOLD, "pilot is on FATIGUE_HOLD", 422)
    a["status"] = "EN_ROUTE"
    a["launched_at"] = fmt_dt(db.clock_now())
    svc.touch(a)
    return success_object(svc.ser_assignment(a))


@bp.post("/assignments/<aid>/arrive")
def arrive_assignment(aid):
    user_id, role = require_roles(["CarrierOps", "Pilot"])
    a = get_assignment_or_404(aid)
    _pilot_ownership_check(user_id, role, a)
    if a["status"] in svc.ASSIGNMENT_TERMINAL:
        raise already_terminal("assignment is DEMOBILIZED (terminal)")
    if a["status"] != "EN_ROUTE":
        raise invalid_state("only an EN_ROUTE assignment may arrive")
    a["status"] = "ON_INCIDENT"
    a["arrived_at"] = fmt_dt(db.clock_now())
    svc.touch(a)
    return success_object(svc.ser_assignment(a))


@bp.post("/assignments/<aid>/release")
def release_assignment(aid):
    require_roles(["AgencyDispatcher"])
    data = body()
    reason = req_enum(data, "release_reason", {"AGENCY", "MECHANICAL"})
    a = get_assignment_or_404(aid)
    if a["status"] in svc.ASSIGNMENT_TERMINAL:
        raise already_terminal("assignment is DEMOBILIZED (terminal)")
    if a["status"] not in ("ASSIGNED", "EN_ROUTE", "ON_INCIDENT"):
        raise invalid_state("only ASSIGNED, EN_ROUTE or ON_INCIDENT assignments may be released")
    a["status"] = "RELEASED"
    a["release_reason"] = reason
    a["released_at"] = fmt_dt(db.clock_now())
    svc.touch(a)
    order = db.dispatch_orders.get(a["dispatch_order_id"])
    if order is not None:
        svc.recompute_order_fill(order)
        svc.touch(order)
    dd = svc.get_duty_day(a["pilot_id"], a["planned_start"].date().isoformat())
    if dd is not None:
        svc.recompute_duty_day(dd)
    return success_object(svc.ser_assignment(a))


@bp.post("/assignments/<aid>/demobilize")
def demobilize_assignment(aid):
    require_roles(["CarrierOps"])
    a = get_assignment_or_404(aid)
    if a["status"] in svc.ASSIGNMENT_TERMINAL:
        raise already_terminal("assignment is DEMOBILIZED (terminal)")
    if a["status"] != "RELEASED":
        raise invalid_state("only a RELEASED assignment may be demobilized")
    a["status"] = "DEMOBILIZED"
    a["demobilized_at"] = fmt_dt(db.clock_now())
    svc.touch(a)
    order = db.dispatch_orders.get(a["dispatch_order_id"])
    if order is not None:
        svc.maybe_close_order(order)
    return success_object(svc.ser_assignment(a))


@bp.get("/assignments/<aid>/flight-logs")
def list_assignment_flight_logs(aid):
    require_roles(ALL_BUSINESS_ROLES)
    get_assignment_or_404(aid)
    items = [f for f in db.flight_logs.values() if f["assignment_id"] == aid]
    return paginate(items, svc.ser_flight_log)


@bp.get("/assignments/<aid>/retardant-loads")
def list_assignment_loads(aid):
    require_roles(ALL_BUSINESS_ROLES)
    get_assignment_or_404(aid)
    items = [l for l in db.retardant_loads.values() if l["assignment_id"] == aid]
    return paginate(items, svc.ser_load)


@bp.get("/assignments/<aid>/agency-records")
def list_assignment_agency_records(aid):
    require_roles(ALL_BUSINESS_ROLES)
    get_assignment_or_404(aid)
    items = [r for r in db.agency_records.values() if r["assignment_id"] == aid]
    return paginate(items, svc.ser_agency_record)


# ===========================================================================
# Flight logs
# ===========================================================================
@bp.post("/assignments/<aid>/flight-logs")
def create_flight_log(aid):
    user_id, role = require_roles(["Pilot"])
    data = body()
    logged_date = req_date(data, "logged_date")
    hobbs_start = req_number(data, "hobbs_start")
    hobbs_stop = req_number(data, "hobbs_stop")
    if not (hobbs_stop > hobbs_start):
        raise bad_request("hobbs_stop must be strictly greater than hobbs_start")

    a = get_assignment_or_404(aid)
    _pilot_ownership_check(user_id, role, a)

    if a["status"] in svc.ASSIGNMENT_TERMINAL:
        raise already_terminal("assignment is DEMOBILIZED (terminal)")
    if a["status"] != "ON_INCIDENT":
        raise invalid_state("flight logs require an ON_INCIDENT assignment")

    order = db.dispatch_orders[a["dispatch_order_id"]]
    contract = db.contracts[order["contract_id"]]

    tenths, billable = svc.sortie_tenths_and_billable(
        hobbs_start, hobbs_stop, contract["flight_hour_rate_cents"]
    )

    # chronological flight-hour gate (priority 8)
    duty_date_str = logged_date.isoformat()
    flown = sum(
        fl["flight_hours_tenths"]
        for fl in db.flight_logs.values()
        if fl["pilot_id"] == a["pilot_id"] and fl["logged_date"] == duty_date_str
    )
    if flown + tenths > svc.DAILY_FLIGHT_LIMIT_TENTHS:
        raise ApiError(ERR_FLIGHT_HOUR_LIMIT_EXCEEDED, "flown_tenths + new log > 80", 422)

    # season cap gate (priority 13)
    if contract["season_flight_hours_tenths"] + tenths > contract["season_flight_hour_cap_tenths"]:
        raise ApiError(ERR_SEASON_FLIGHT_CAP_EXCEEDED, "season flight-hour cap exceeded", 422)

    now = db.iso_now_ms()
    fl = {
        "id": db.new_id(),
        "created_at": now,
        "assignment_id": aid,
        "pilot_id": a["pilot_id"],
        "logged_date": duty_date_str,
        "hobbs_start": hobbs_start,
        "hobbs_stop": hobbs_stop,
        "flight_hours_tenths": tenths,
        "billable_cents": billable,
    }
    db.stamp_new(fl)
    db.flight_logs[fl["id"]] = fl

    # season hours on contract (+version)
    svc.recompute_contract_season_hours(contract)
    svc.touch(contract)

    # duty day auto-create + recompute
    dd = svc.get_duty_day(a["pilot_id"], duty_date_str)
    if dd is None:
        dd = svc.create_duty_day(a["pilot_id"], duty_date_str, None)
    svc.recompute_duty_day(dd)

    # fatigue trigger + cascade
    crew = db.crew_members[a["pilot_id"]]
    if dd["flown_tenths"] >= svc.DAILY_FLIGHT_LIMIT_TENTHS:
        svc.fire_fatigue_cascade(crew, dd)

    # re-derive covering DRAFT invoices
    svc.rederive_covering_draft_invoices(contract["id"], duty_date_str)

    return success_object(svc.ser_flight_log(fl), 201)


# ===========================================================================
# Retardant loads
# ===========================================================================
@bp.post("/assignments/<aid>/retardant-loads")
def create_retardant_load(aid):
    require_roles(["CarrierOps"])
    data = body()
    gallons = req_int(data, "gallons")
    if gallons <= 0:
        raise bad_request("gallons must be > 0")
    requested_at = opt_datetime(data, "requested_at", None)

    a = get_assignment_or_404(aid)
    if a["status"] in svc.ASSIGNMENT_TERMINAL:
        raise already_terminal("assignment is DEMOBILIZED (terminal)")
    if a["status"] != "ON_INCIDENT":
        raise invalid_state("retardant loads require an ON_INCIDENT assignment")

    aircraft = db.aircraft[a["aircraft_id"]]
    if gallons > aircraft["tank_capacity_gallons"]:
        raise ApiError(ERR_TANK_CAPACITY_EXCEEDED, "gallons > tank_capacity_gallons", 422)

    if requested_at is None:
        requested_at = db.clock_now()
    now = db.iso_now_ms()
    l = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "assignment_id": aid,
        "gallons": gallons,
        "requested_at": requested_at,
        "loaded_at": None,
        "dropped_at": None,
        "status": "REQUESTED",
        "reload_turn_minutes": None,
    }
    db.stamp_new(l)
    db.retardant_loads[l["id"]] = l
    return success_object(svc.ser_load(l), 201)


@bp.post("/retardant-loads/<lid>/load")
def complete_load(lid):
    require_roles(["CarrierOps"])
    data = body()
    loaded_at = req_datetime(data, "loaded_at")
    l = get_load_or_404(lid)
    if l["status"] in svc.LOAD_TERMINAL:
        raise already_terminal("retardant load is DROPPED (terminal)")
    if l["status"] != "REQUESTED":
        raise invalid_state("only a REQUESTED load may be loaded")
    if loaded_at < l["requested_at"]:
        raise invalid_state("loaded_at must be >= requested_at")
    l["status"] = "LOADED"
    l["loaded_at"] = loaded_at
    l["reload_turn_minutes"] = svc.compute_reload_turn(l, l["assignment_id"])
    svc.touch(l)
    assignment = db.assignments[l["assignment_id"]]
    svc.recompute_assignment_reload_fields(assignment)
    svc.touch(assignment)
    return success_object(svc.ser_load(l))


@bp.post("/retardant-loads/<lid>/drop")
def drop_load(lid):
    user_id, role = require_roles(["CarrierOps", "Pilot"])
    data = body()
    dropped_at = req_datetime(data, "dropped_at")
    l = get_load_or_404(lid)
    assignment = db.assignments[l["assignment_id"]]
    _pilot_ownership_check(user_id, role, assignment)
    if l["status"] in svc.LOAD_TERMINAL:
        raise already_terminal("retardant load is DROPPED (terminal)")
    if l["status"] != "LOADED":
        raise invalid_state("only a LOADED load may be dropped")
    if dropped_at < l["loaded_at"]:
        raise invalid_state("dropped_at must be >= loaded_at")
    l["status"] = "DROPPED"
    l["dropped_at"] = dropped_at
    svc.touch(l)
    return success_object(svc.ser_load(l))


# ===========================================================================
# Invoices
# ===========================================================================
@bp.post("/contracts/<cid>/invoices")
def create_invoice(cid):
    require_roles(["CarrierFinance"])
    data = body()
    period_start = req_date(data, "period_start")
    period_end = req_date(data, "period_end")
    if period_end < period_start:
        raise bad_request("period_end must be on or after period_start")
    expected_version = data.get("expected_contract_version")
    if expected_version is not None and (isinstance(expected_version, bool) or not isinstance(expected_version, int)):
        raise bad_request("expected_contract_version must be an integer")

    contract = get_contract_or_404(cid)

    # (6) OCC
    if expected_version is not None and expected_version != contract["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_contract_version is stale", 412)

    # (7) state
    if contract["status"] in svc.CONTRACT_TERMINAL:
        raise already_terminal("contract is CLOSED (terminal)")
    if contract["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACT_NOT_ACTIVE, "contract is not ACTIVE", 409)

    # (9) uniqueness: one non-VOID invoice per (contract_id, period_start)
    for inv in db.invoices.values():
        if (
            inv["contract_id"] == cid
            and inv["period_start"] == period_start.isoformat()
            and inv["status"] != "VOID"
        ):
            raise ApiError(ERR_INVOICE_PERIOD_OVERLAP, "a non-VOID invoice already exists for (contract_id, period_start)", 409)

    now = db.iso_now_ms()
    inv = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "contract_id": cid,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "status": "DRAFT",
        "billing_basis": "PROVISIONAL",
        "availability_subtotal_cents": 0,
        "flight_subtotal_cents": 0,
        "penalty_cents": 0,
        "net_cents": 0,
        "submitted_by": None,
        "submitted_at": None,
        "reconciled_by": None,
        "dispute_reason": None,
    }
    db.stamp_new(inv)
    db.invoices[inv["id"]] = inv
    svc.rederive_invoice(inv)
    # creation bumps the contract's version
    svc.touch(contract)
    return success_object(svc.ser_invoice(inv), 201)


@bp.get("/invoices/<iid>")
def get_invoice(iid):
    require_roles(ALL_BUSINESS_ROLES)
    return success_object(svc.ser_invoice(get_invoice_or_404(iid)))


@bp.get("/invoices/<iid>/line-items")
def list_invoice_line_items(iid):
    require_roles(ALL_BUSINESS_ROLES)
    get_invoice_or_404(iid)
    items = [li for li in db.invoice_line_items.values() if li["invoice_id"] == iid]
    lt = request.args.get("line_type")
    if lt is not None:
        items = [li for li in items if li["line_type"] == lt]
    return paginate(items, svc.ser_line_item)


@bp.post("/invoices/<iid>/submit")
def submit_invoice(iid):
    user_id, role = require_roles(["CarrierFinance"])
    inv = get_invoice_or_404(iid)
    if inv["status"] in svc.INVOICE_TERMINAL:
        raise already_terminal(f"invoice is {inv['status']} (terminal)")
    if inv["status"] != "DRAFT":
        raise invalid_state("only a DRAFT invoice may be submitted")
    if not (str_to_date(inv["period_end"]) < db.clock_now().date()):
        raise ApiError(ERR_BILLING_PERIOD_NOT_CLOSED, "billing period is not closed", 422)
    contract = db.contracts[inv["contract_id"]]
    inv["status"] = "SUBMITTED"
    inv["submitted_by"] = user_id
    inv["submitted_at"] = fmt_dt(db.clock_now())
    contract["season_billed_cents"] += inv["net_cents"]
    svc.touch(contract)
    svc.touch(inv)
    return success_object(svc.ser_invoice(inv))


@bp.post("/invoices/<iid>/dispute")
def dispute_invoice(iid):
    require_roles(["AgencyFinance"])
    data = body()
    reason = req_str(data, "dispute_reason")
    inv = get_invoice_or_404(iid)
    if inv["status"] in svc.INVOICE_TERMINAL:
        raise already_terminal(f"invoice is {inv['status']} (terminal)")
    if inv["status"] != "SUBMITTED":
        raise invalid_state("only a SUBMITTED invoice may be disputed")
    inv["status"] = "DISPUTED"
    inv["dispute_reason"] = reason
    svc.touch(inv)
    return success_object(svc.ser_invoice(inv))


@bp.post("/invoices/<iid>/resubmit")
def resubmit_invoice(iid):
    user_id, role = require_roles(["CarrierFinance"])
    inv = get_invoice_or_404(iid)
    if inv["status"] in svc.INVOICE_TERMINAL:
        raise already_terminal(f"invoice is {inv['status']} (terminal)")
    if inv["status"] != "DISPUTED":
        raise invalid_state("only a DISPUTED invoice may be resubmitted")
    inv["status"] = "SUBMITTED"
    inv["dispute_reason"] = None
    inv["submitted_by"] = user_id
    inv["submitted_at"] = fmt_dt(db.clock_now())
    svc.touch(inv)
    return success_object(svc.ser_invoice(inv))


@bp.post("/invoices/<iid>/reconcile")
def reconcile_invoice(iid):
    user_id, role = require_roles(["AgencyFinance"])
    inv = get_invoice_or_404(iid)
    if inv["status"] in svc.INVOICE_TERMINAL:
        raise already_terminal(f"invoice is {inv['status']} (terminal)")
    if inv["status"] != "SUBMITTED":
        raise invalid_state("only a SUBMITTED invoice may be reconciled")
    if inv["submitted_by"] is not None and user_id == inv["submitted_by"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, "reconciler must differ from submitter", 403)

    contract = db.contracts[inv["contract_id"]]
    lines = [li for li in db.invoice_line_items.values() if li["invoice_id"] == inv["id"]]
    any_mismatch = False
    for li in lines:
        if li["line_type"] == "FLIGHT_DAY":
            match = None
            for r in db.agency_records.values():
                if (
                    r["contract_id"] == contract["id"]
                    and r["assignment_id"] == li["source_ref_id"]
                    and r["record_date"] == li["reference_date"]
                ):
                    match = r
                    break
            if match is not None:
                li["agency_qty"] = match["agency_flight_hours_tenths"]
                li["agency_amount_cents"] = int(
                    (
                        __import__("decimal").Decimal(match["agency_flight_hours_tenths"])
                        / __import__("decimal").Decimal(10)
                        * __import__("decimal").Decimal(contract["flight_hour_rate_cents"])
                    ).quantize(__import__("decimal").Decimal("1"), rounding=__import__("decimal").ROUND_HALF_UP)
                )
                li["mismatch_flag"] = abs(li["carrier_qty"] - li["agency_qty"]) > svc.MATCH_TOLERANCE_TENTHS
                if li["mismatch_flag"]:
                    any_mismatch = True
            else:
                li["agency_qty"] = li["carrier_qty"]
                li["agency_amount_cents"] = li["carrier_amount_cents"]
                li["mismatch_flag"] = False
        else:
            li["agency_amount_cents"] = li["carrier_amount_cents"]
            li["mismatch_flag"] = False

    if any_mismatch:
        inv["status"] = "DISPUTED"
        inv["dispute_reason"] = "RECONCILIATION_MISMATCH"
        svc.touch(inv)
        return success_object(svc.ser_invoice(inv))

    old_net = inv["net_cents"]
    inv["status"] = "RECONCILED"
    inv["billing_basis"] = "RECONCILED"
    inv["reconciled_by"] = user_id
    for li in lines:
        if li["line_type"] == "FLIGHT_DAY":
            li["billed_amount_cents"] = li["agency_amount_cents"]
    svc.recompute_invoice_totals(inv)
    contract["season_billed_cents"] += (inv["net_cents"] - old_net)
    svc.touch(contract)
    svc.touch(inv)
    return success_object(svc.ser_invoice(inv))


@bp.post("/invoices/<iid>/mark-paid")
def mark_paid_invoice(iid):
    require_roles(["AgencyFinance"])
    inv = get_invoice_or_404(iid)
    if inv["status"] in svc.INVOICE_TERMINAL:
        raise already_terminal(f"invoice is {inv['status']} (terminal)")
    if inv["status"] != "RECONCILED":
        raise invalid_state("only a RECONCILED invoice may be marked paid")
    inv["status"] = "PAID"
    svc.touch(inv)
    return success_object(svc.ser_invoice(inv))


@bp.post("/invoices/<iid>/void")
def void_invoice(iid):
    require_roles(["CarrierFinance"])
    inv = get_invoice_or_404(iid)
    if inv["status"] in svc.INVOICE_TERMINAL:
        raise already_terminal(f"invoice is {inv['status']} (terminal)")
    if inv["status"] not in ("DRAFT", "SUBMITTED", "DISPUTED"):
        raise invalid_state("only DRAFT, SUBMITTED or DISPUTED invoices may be voided")
    contract = db.contracts[inv["contract_id"]]
    if inv["status"] in ("SUBMITTED", "DISPUTED"):
        contract["season_billed_cents"] -= inv["net_cents"]
        svc.touch(contract)
    inv["status"] = "VOID"
    svc.touch(inv)
    return success_object(svc.ser_invoice(inv))


# ===========================================================================
# Agency records
# ===========================================================================
@bp.post("/agency-records")
def create_agency_record():
    require_roles(["AgencyFinance"])
    data = body()
    contract_id = req_str(data, "contract_id")
    assignment_id = req_str(data, "assignment_id")
    record_date = req_date(data, "record_date")
    tenths = req_int(data, "agency_flight_hours_tenths")
    if tenths < 0:
        raise bad_request("agency_flight_hours_tenths must be >= 0")
    minutes = opt_int(data, "agency_available_minutes", None)

    get_contract_or_404(contract_id)
    get_assignment_or_404(assignment_id)

    now = db.iso_now_ms()
    r = {
        "id": db.new_id(),
        "created_at": now,
        "contract_id": contract_id,
        "assignment_id": assignment_id,
        "record_date": record_date.isoformat(),
        "agency_flight_hours_tenths": tenths,
        "agency_available_minutes": minutes,
    }
    db.stamp_new(r)
    db.agency_records[r["id"]] = r
    return success_object(svc.ser_agency_record(r), 201)


# ===========================================================================
# Logical clock
# ===========================================================================
@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles(["SystemAdmin"])
    data = body()
    to_iso8601 = req_str(data, "to_iso8601")
    dt = parse_datetime(to_iso8601, "to_iso8601")
    db.set_clock(dt)
    return success_object({"current_utc": fmt_dt(db.clock_now())})
