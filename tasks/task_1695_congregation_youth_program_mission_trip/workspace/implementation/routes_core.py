"""Logical clock, programs, and trips."""
from flask import request

from store import DB
from util import (
    ApiError, success_object, get_body, req_str, opt_str, req_int, opt_int,
    req_enum, req_datetime, req_date, fmt_clock, trip_end_instant, trip_start_instant,
)
import domain as D
from web import (
    app, PREFIX, ALL_ROLES, caller, require_role, paginate, get_program, get_trip,
)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@app.post(f"{PREFIX}/_clock/set-current-utc")
def set_clock():
    uid, role = caller()
    body = get_body()
    raw, dt = req_datetime(body, "to_iso8601")
    require_role(role, ["ProgramDirector"])
    DB.clock_dt = dt
    D.delinquency_sweep()
    D.screening_expiry_sweep()
    return success_object({})


# ---------------------------------------------------------------------------
# Programs
# ---------------------------------------------------------------------------

@app.post(f"{PREFIX}/programs")
def create_program():
    uid, role = caller()
    body = get_body()
    name = req_str(body, "name")
    ministry_year = req_str(body, "ministry_year")
    fund_total = req_int(body, "scholarship_fund_total_cents", min_value=0)
    conduct = req_str(body, "code_of_conduct_text")
    discipline = req_str(body, "discipline_policy_text")
    max_award = opt_int(body, "max_award_pct_bp", min_value=0, max_value=10000)
    per_cap = opt_int(body, "per_registration_cap_cents", min_value=0)
    ratio = opt_int(body, "default_chaperone_ratio", min_value=1)
    require_role(role, ["ProgramDirector"])

    program = {
        "name": name,
        "ministry_year": ministry_year,
        "status": "OPEN",
        "scholarship_fund_total_cents": fund_total,
        "scholarship_reserved_cents": 0,
        "scholarship_disbursed_cents": 0,
        "scholarship_available_cents": fund_total,
        "max_award_pct_bp": 5000 if max_award is None else max_award,
        "per_registration_cap_cents": 150000 if per_cap is None else per_cap,
        "default_chaperone_ratio": 5 if ratio is None else ratio,
        "code_of_conduct_text": conduct,
        "discipline_policy_text": discipline,
    }
    DB.stamp_created(program)
    DB.programs[program["id"]] = program
    return success_object(D.ser_program(program), 201)


@app.get(f"{PREFIX}/programs/<pid>")
def read_program(pid):
    uid, role = caller()
    require_role(role, ALL_ROLES)
    program = get_program(pid)
    return success_object(D.ser_program(program))


@app.put(f"{PREFIX}/programs/<pid>/scholarship-policy")
def put_scholarship_policy(pid):
    uid, role = caller()
    body = get_body()
    max_award = req_int(body, "max_award_pct_bp", min_value=0, max_value=10000)
    per_cap = req_int(body, "per_registration_cap_cents", min_value=0)
    expected = req_int(body, "expected_program_version")
    require_role(role, ["ProgramDirector"])
    program = get_program(pid)
    if expected != program["version"]:
        raise ApiError("ERR_STALE_PROGRAM_VERSION", "Program version has advanced", 412)
    program["max_award_pct_bp"] = max_award
    program["per_registration_cap_cents"] = per_cap
    DB.touch("programs", program["id"])
    D.recompute_program_fund(program)
    return success_object(D.ser_program(program))


@app.post(f"{PREFIX}/programs/<pid>/close")
def close_program(pid):
    uid, role = caller()
    require_role(role, ["ProgramDirector"])
    program = get_program(pid)
    if program["status"] != "OPEN":
        raise ApiError("ERR_PROGRAM_NOT_OPEN", "Program is not OPEN", 409)
    for trip in DB.trips.values():
        if trip["program_id"] == pid and trip["status"] not in ("DEBRIEFED", "CANCELLED"):
            raise ApiError("ERR_PROGRAM_HAS_OPEN_TRIPS", "Some trips are not DEBRIEFED or CANCELLED", 409)
    program["status"] = "CLOSED"
    DB.touch("programs", program["id"])
    return success_object(D.ser_program(program))


# ---------------------------------------------------------------------------
# Trips
# ---------------------------------------------------------------------------

INSURANCE_BY_DESTINATION = {"IN_STATE": "NONE", "OUT_OF_STATE": "DOMESTIC", "INTERNATIONAL": "INTERNATIONAL"}


@app.post(f"{PREFIX}/trips")
def create_trip():
    uid, role = caller()
    body = get_body()
    program_id = req_str(body, "program_id")
    name = req_str(body, "name")
    destination_name = req_str(body, "destination_name")
    destination_type = req_enum(body, "destination_type", D.DESTINATION_TYPES)
    start_raw, start_d = req_date(body, "start_date")
    end_raw, end_d = req_date(body, "end_date")
    capacity = req_int(body, "capacity_youth", min_value=1)
    base_cost = req_int(body, "base_cost_cents", min_value=0)
    deposit = req_int(body, "deposit_cents", min_value=0)
    chaperone_ratio = req_int(body, "chaperone_ratio", min_value=1)
    open_raw, open_dt = req_datetime(body, "registration_open_at")
    close_raw, close_dt = req_datetime(body, "registration_close_at")
    dep_raw, dep_dt = req_datetime(body, "deposit_due_at")
    fin_raw, fin_dt = req_datetime(body, "final_payment_due_at")
    emergency = opt_str(body, "emergency_protocol_text", "")
    if end_d <= start_d:
        raise ApiError("ERR_INVALID_DATE_RANGE", "end_date must be strictly after start_date", 400)
    if deposit > base_cost:
        raise ApiError("ERR_INVALID_REQUEST", "deposit_cents may not exceed base_cost_cents", 400)
    require_role(role, ["ProgramDirector"])
    program = get_program(program_id)
    if program["status"] != "OPEN":
        raise ApiError("ERR_PROGRAM_NOT_OPEN", "Program is not OPEN", 409)
    if chaperone_ratio > program["default_chaperone_ratio"]:
        raise ApiError("ERR_INVALID_REQUEST",
                       "chaperone_ratio may not exceed the program default_chaperone_ratio", 400)

    trip = {
        "program_id": program_id,
        "name": name,
        "destination_name": destination_name,
        "destination_type": destination_type,
        "start_date": start_raw,
        "end_date": end_raw,
        "capacity_youth": capacity,
        "base_cost_cents": base_cost,
        "deposit_cents": deposit,
        "chaperone_ratio": chaperone_ratio,
        "required_insurance_tier": INSURANCE_BY_DESTINATION[destination_type],
        "registration_open_at": fmt_clock(open_dt),
        "registration_close_at": fmt_clock(close_dt),
        "deposit_due_at": fmt_clock(dep_dt),
        "final_payment_due_at": fmt_clock(fin_dt),
        "emergency_protocol_text": emergency,
        "status": "DRAFT",
        "seats_taken": 0,
        "confirmed_youth_count": 0,
        "cleared_chaperone_count": 0,
        "required_cleared_chaperones": 0,
        "ratio_compliant": True,
        "lodging_cost_total_cents": 0,
        "debrief_summary": "",
        "debrief_actual_participant_count": 0,
        "debrief_incident_count": 0,
        "debrief_lessons_learned": "",
        "debriefed_at": "",
        "_locked": False,
        "_deposit_due_dt": dep_dt,
        "_final_payment_due_dt": fin_dt,
        "_registration_open_dt": open_dt,
        "_registration_close_dt": close_dt,
    }
    DB.stamp_created(trip)
    DB.trips[trip["id"]] = trip
    return success_object(D.ser_trip(trip), 201)


@app.get(f"{PREFIX}/trips")
def list_trips():
    uid, role = caller()
    require_role(role, ALL_ROLES)
    items = list(DB.trips.values())
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    if program_id is not None:
        items = [t for t in items if t["program_id"] == program_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    return paginate(items, D.ser_trip)


@app.get(f"{PREFIX}/trips/<tid>")
def read_trip(tid):
    uid, role = caller()
    require_role(role, ALL_ROLES)
    trip = get_trip(tid)
    return success_object(D.ser_trip(trip))


@app.patch(f"{PREFIX}/trips/<tid>")
def patch_trip(tid):
    uid, role = caller()
    body = get_body()
    name = opt_str(body, "name", None)
    capacity = opt_int(body, "capacity_youth", min_value=1)
    ratio = opt_int(body, "chaperone_ratio", min_value=1)
    emergency = opt_str(body, "emergency_protocol_text", None)
    expected = req_int(body, "expected_trip_version")
    require_role(role, ["ProgramDirector"])
    trip = get_trip(tid)
    if trip["status"] in ("IN_PROGRESS", "DEBRIEFED", "CANCELLED"):
        raise ApiError("ERR_TRIP_STATE_FORBIDS_ACTION",
                       "Trip edits are not permitted once IN_PROGRESS or later", 409)
    if expected != trip["version"]:
        raise ApiError("ERR_STALE_TRIP_VERSION", "Trip version has advanced", 412)
    if capacity is not None:
        D.recompute_trip(trip)
        if capacity < trip["seats_taken"]:
            raise ApiError("ERR_CAPACITY_FLOOR", "capacity_youth may not drop below seats_taken", 409)
    if ratio is not None:
        program = get_program(trip["program_id"])
        if ratio > program["default_chaperone_ratio"]:
            raise ApiError("ERR_INVALID_REQUEST",
                           "chaperone_ratio may not exceed the program default_chaperone_ratio", 400)

    capacity_changed = capacity is not None and capacity != trip["capacity_youth"]
    if name is not None:
        trip["name"] = name
    if capacity is not None:
        trip["capacity_youth"] = capacity
    if ratio is not None:
        trip["chaperone_ratio"] = ratio
    if emergency is not None:
        trip["emergency_protocol_text"] = emergency
    DB.touch("trips", trip["id"])
    D.recompute_trip(trip)
    if capacity_changed:
        D.recompute_provisional_shares(trip)
    return success_object(D.ser_trip(trip))


@app.post(f"{PREFIX}/trips/<tid>/open-registration")
def open_registration(tid):
    uid, role = caller()
    require_role(role, ["ProgramDirector"])
    trip = get_trip(tid)
    if trip["status"] != "DRAFT":
        raise ApiError("ERR_TRIP_STATE_FORBIDS_ACTION", "Trip is not DRAFT", 409)
    program = get_program(trip["program_id"])
    if program["status"] != "OPEN":
        raise ApiError("ERR_PROGRAM_NOT_OPEN", "Program is not OPEN", 409)
    if DB.clock_dt < trip["_registration_open_dt"]:
        raise ApiError("ERR_REGISTRATION_WINDOW_CLOSED",
                       "Registration may not open before registration_open_at", 422)
    trip["status"] = "REGISTRATION_OPEN"
    DB.touch("trips", trip["id"])
    return success_object(D.ser_trip(trip))


@app.post(f"{PREFIX}/trips/<tid>/close-registration")
def close_registration(tid):
    uid, role = caller()
    require_role(role, ["ProgramDirector"])
    trip = get_trip(tid)
    if trip["status"] != "REGISTRATION_OPEN":
        raise ApiError("ERR_TRIP_STATE_FORBIDS_ACTION", "Trip is not REGISTRATION_OPEN", 409)
    trip["status"] = "REGISTRATION_CLOSED"
    DB.touch("trips", trip["id"])
    return success_object(D.ser_trip(trip))


def _participant_created_at(reg):
    p = DB.participants.get(reg["participant_id"])
    return p["created_at"] if p is not None else ""


@app.post(f"{PREFIX}/trips/<tid>/lock-roster")
def lock_roster(tid):
    uid, role = caller()
    require_role(role, ["ProgramDirector"])
    trip = get_trip(tid)
    if trip["status"] != "REGISTRATION_CLOSED":
        raise ApiError("ERR_TRIP_STATE_FORBIDS_ACTION", "Trip is not REGISTRATION_CLOSED", 409)
    D.recompute_trip(trip)
    # SAFETY: chaperone ratio (vacuously satisfied with zero confirmed youth)
    if not trip["ratio_compliant"]:
        raise ApiError("ERR_CHAPERONE_RATIO_UNMET", "Cleared chaperone ratio is not met", 422)
    confirmed = [r for r in D.regs_of_trip(tid) if r["registration_status"] == "CONFIRMED"]
    # SAFETY: insurance tiers on CONFIRMED registrations
    required_rank = D.INSURANCE_RANK[trip["required_insurance_tier"]]
    for reg in confirmed:
        if D.INSURANCE_RANK[reg["insurance_tier"]] < required_rank:
            raise ApiError("ERR_INSURANCE_TIER_INSUFFICIENT",
                           "A CONFIRMED registration's insurance_tier is insufficient", 422)
    # REFERENTIAL: non-empty roster
    if trip["confirmed_youth_count"] < 1:
        raise ApiError("ERR_EMPTY_ROSTER", "Cannot lock an empty roster", 422)
    # CONSTRAINT: emergency protocol
    if trip["destination_type"] != "IN_STATE" and not trip["emergency_protocol_text"]:
        raise ApiError("ERR_EMERGENCY_PROTOCOL_MISSING", "Emergency protocol text is required", 422)
    # CONSTRAINT: lodging capacity
    beds = sum(r["room_capacity"] for r in DB.lodging_reservations.values()
               if r["trip_id"] == tid and r["status"] == "CONFIRMED")
    if beds < trip["confirmed_youth_count"] + trip["cleared_chaperone_count"]:
        raise ApiError("ERR_LODGING_CAPACITY_INSUFFICIENT", "Confirmed lodging beds are insufficient", 422)
    # FISCAL: deposit coverage, checked last
    for reg in confirmed:
        D.registration_money(reg, trip, update_status=False)
        if reg["covered_cents"] < trip["deposit_cents"]:
            raise ApiError("ERR_UNPAID_BALANCES_REMAIN",
                           "A CONFIRMED registration has not covered the deposit", 402)

    # Final cost shares: created_at ASC, tie-break participant created_at ASC
    ordered = sorted(
        confirmed,
        key=lambda r: (r["created_at"], _participant_created_at(r), r["_seq"]),
    )
    D.compute_final_cost_shares(trip, ordered)
    trip["_locked"] = True
    for reg in confirmed:
        DB.touch("registrations", reg["id"])
        covered = reg["covered_cents"]
        due_total = reg["final_cost_share_cents"] + reg["late_fees_total_cents"]
        reg["amount_due_cents"] = max(0, due_total - covered)
        if reg["payment_status"] != "REFUNDED":
            if due_total > 0 and covered >= due_total:
                reg["payment_status"] = "PAID_IN_FULL"
            elif covered >= trip["deposit_cents"]:
                reg["payment_status"] = "PARTIALLY_PAID"
            else:
                reg["payment_status"] = "PENDING_DEPOSIT"
    trip["status"] = "ROSTER_LOCKED"
    DB.touch("trips", trip["id"])
    D.recompute_trip(trip)
    return success_object(D.ser_trip(trip))


@app.post(f"{PREFIX}/trips/<tid>/start")
def start_trip(tid):
    uid, role = caller()
    require_role(role, ["ProgramDirector"])
    trip = get_trip(tid)
    if trip["status"] != "ROSTER_LOCKED":
        raise ApiError("ERR_TRIP_STATE_FORBIDS_ACTION", "Trip is not ROSTER_LOCKED", 409)
    D.recompute_trip(trip)
    if not trip["ratio_compliant"]:
        raise ApiError("ERR_CHAPERONE_RATIO_UNMET", "Cleared chaperone ratio is not met", 422)
    if DB.clock_dt < trip_start_instant(trip["start_date"]):
        raise ApiError("ERR_TRIP_STATE_FORBIDS_ACTION", "Trip start instant not reached", 409)
    trip["status"] = "IN_PROGRESS"
    DB.touch("trips", trip["id"])
    return success_object(D.ser_trip(trip))


@app.post(f"{PREFIX}/trips/<tid>/debrief")
def debrief_trip(tid):
    uid, role = caller()
    body = get_body()
    summary = req_str(body, "debrief_summary")
    actual_count = req_int(body, "debrief_actual_participant_count", min_value=0)
    incident_count = req_int(body, "debrief_incident_count", min_value=0)
    lessons = req_str(body, "debrief_lessons_learned")
    require_role(role, ["ProgramDirector"])
    trip = get_trip(tid)
    if trip["status"] != "IN_PROGRESS":
        raise ApiError("ERR_TRIP_STATE_FORBIDS_ACTION", "Trip is not IN_PROGRESS", 409)
    if DB.clock_dt < trip_end_instant(trip["end_date"]):
        raise ApiError("ERR_TRIP_STATE_FORBIDS_ACTION", "Trip end instant not reached", 409)
    trip["debrief_summary"] = summary
    trip["debrief_actual_participant_count"] = actual_count
    trip["debrief_incident_count"] = incident_count
    trip["debrief_lessons_learned"] = lessons
    trip["debriefed_at"] = DB.clock_string()
    trip["status"] = "DEBRIEFED"
    DB.touch("trips", trip["id"])
    for reg in D.regs_of_trip(tid):
        if reg["registration_status"] == "CONFIRMED":
            reg["registration_status"] = "COMPLETED"
            DB.touch("registrations", reg["id"])
            account = D.account_of_registration(reg["id"])
            if account is not None and account["status"] == "OPEN":
                account["status"] = "CLOSED"
                DB.touch("fundraising_accounts", account["id"])
    D.recompute_trip(trip)
    return success_object(D.ser_trip(trip))


@app.post(f"{PREFIX}/trips/<tid>/cancel")
def cancel_trip(tid):
    uid, role = caller()
    require_role(role, ["ProgramDirector"])
    trip = get_trip(tid)
    if trip["status"] in ("DEBRIEFED", "CANCELLED"):
        raise ApiError("ERR_TRIP_STATE_FORBIDS_ACTION", "Trip is already terminal", 409)
    if trip["status"] != "DRAFT":
        D.trip_cancel_cascade(trip)
    trip["status"] = "CANCELLED"
    DB.touch("trips", trip["id"])
    D.recompute_trip(trip)
    return success_object(D.ser_trip(trip))
