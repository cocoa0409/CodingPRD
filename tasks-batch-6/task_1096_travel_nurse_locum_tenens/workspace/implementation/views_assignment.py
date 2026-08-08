"""Assignments, contracts, and extension negotiations."""
import uuid

from app import app
from store import store
from common import (
    ApiError, ok, ok_list, authenticate, authorize, body, verr,
    req_str, opt_str, req_enum, opt_enum, req_int, opt_bool, req_state_code,
    req_date, req_sunday, new_common, touch, pagination, paginate, READ_ROLES,
    fine_authz, check_ownership, D, add_days, date_le,
)
from serializers import ser_assignment, ser_contract, ser_extension
from domain import (
    SPECIALTIES, LICENSE_TYPES, SHIFTS, license_coverage, compute_projected,
    compute_readiness, recompute_end_date, apply_clinician_recompute,
    perform_cancellation, accept_extension, withdraw_open_extensions,
    MAX_TERM_WEEKS,
)


def _uuid():
    return str(uuid.uuid4())


def _filter(name):
    from flask import request
    v = request.args.get(name)
    return v if v not in (None, "") else None


def _contract_of(assignment_id):
    for c in store.contracts.values():
        if c["assignment_id"] == assignment_id:
            return c
    return None


# ===========================================================================
# POST /assignments
# ===========================================================================
@app.route("/assignments", methods=["POST"])
def create_assignment():
    _uid, role = authenticate()
    authorize(role, ["Recruiter"])
    b = body()
    clinician_id = req_str(b, "clinician_id")
    facility_id = req_str(b, "facility_id")
    specialty = req_enum(b, "specialty", SPECIALTIES)
    required_license_type = req_enum(b, "required_license_type", LICENSE_TYPES)
    start_date = req_sunday(b, "start_date")
    term_weeks = req_int(b, "term_weeks")
    if term_weeks < 1 or term_weeks > MAX_TERM_WEEKS:
        verr("term_weeks must be between 1 and 26")
    weekly = _req_weekly(b, "weekly_guaranteed_hours")
    base_pay = req_int(b, "base_pay_rate_cents_per_hour")
    bill_rate = req_int(b, "bill_rate_cents_per_hour")
    shift = opt_enum(b, "shift", SHIFTS, "DAY")

    # Body FK resolution (priority 6)
    clinician = store.clinicians.get(clinician_id)
    if not clinician:
        raise ApiError("ERR_CLINICIAN_NOT_FOUND", 404, "Clinician not found")
    facility = store.facilities.get(facility_id)
    if not facility:
        raise ApiError("ERR_FACILITY_NOT_FOUND", 404, "Facility not found")

    # Specialty must equal clinician's specialty (ERR_VALIDATION)
    if specialty != clinician["specialty"]:
        verr("specialty must equal the clinician's specialty")

    end_date = add_days(start_date, term_weeks * 7 - 1)

    # Build a transient assignment view for coverage resolution
    probe = {"clinician_id": clinician_id, "facility_id": facility_id,
             "required_license_type": required_license_type}
    covering = license_coverage(probe, end_date)
    if covering is None:
        raise ApiError("ERR_LICENSE_COVERAGE_MISSING", 422, "No covering license for the term")

    # Clinician schedule conflict (priority 15), buffered by 2 days each side
    ns_m2 = add_days(start_date, -2)
    ne_p2 = add_days(end_date, 2)
    for a in store.assignments.values():
        if a["clinician_id"] != clinician_id:
            continue
        if a["staffing_status"] not in ("DRAFT", "PENDING_START", "ACTIVE"):
            continue
        if date_le(ns_m2, a["end_date"]) and date_le(a["start_date"], ne_p2):
            raise ApiError("ERR_CLINICIAN_SCHEDULE_CONFLICT", 409, "Schedule conflict")

    # Facility capacity (priority 17), unbuffered intersection
    overlap = 0
    for a in store.assignments.values():
        if a["facility_id"] != facility_id:
            continue
        if a["staffing_status"] not in ("PENDING_START", "ACTIVE"):
            continue
        if date_le(a["start_date"], end_date) and date_le(start_date, a["end_date"]):
            overlap += 1
    if overlap >= facility["max_concurrent_travelers"]:
        raise ApiError("ERR_FACILITY_CAPACITY_EXCEEDED", 409, "Facility capacity exceeded")

    total_hours = D(weekly) * term_weeks
    a = new_common(True)
    a["id"] = _uuid()
    a.update({
        "clinician_id": clinician_id, "facility_id": facility_id,
        "covering_license_id": covering,
        "specialty": specialty, "required_license_type": required_license_type,
        "shift": shift, "start_date": start_date, "term_weeks": term_weeks,
        "end_date": end_date, "staffing_status": "DRAFT",
        "compliance_status": "PENDING_CREDENTIALS",
        "guaranteed_hours_total": total_hours,
        "guaranteed_hours_consumed": D("0"),
        "guaranteed_hours_remaining": total_hours,
        "guaranteed_hours_waived": D("0"),
        "realized_gross_bill_cents": 0, "realized_pay_cost_cents": 0,
        "realized_margin_cents": 0, "realized_margin_pct": D("0"),
        "projected_gross_bill_cents": 0, "projected_pay_cost_cents": 0,
        "projected_margin_cents": 0, "projected_margin_pct": D("0"),
        "extension_round_count": 0,
        "cancellation_effective_date": None,
        "cancellation_notice_days": None,
        "cancellation_penalty_cents": None,
    })
    store.assignments[a["id"]] = a

    c = new_common(True)
    c["id"] = _uuid()
    c.update({
        "assignment_id": a["id"], "status": "DRAFT", "term_weeks": term_weeks,
        "weekly_guaranteed_hours": D(weekly),
        "base_pay_rate_cents_per_hour": base_pay,
        "bill_rate_cents_per_hour": bill_rate,
        "revision_count": 0, "countersign_note": None,
        "clinician_signed_at": None, "voided_reason": None,
    })
    store.contracts[c["id"]] = c

    p = new_common(True)
    p["id"] = _uuid()
    p.update({
        "assignment_id": a["id"], "status": "DRAFT",
        "readiness_score_start_basis": 0, "blocking_item_count_start_basis": 5,
        "readiness_score_full_term_basis": 0, "blocking_item_count_full_term_basis": 5,
        "revision_round": 0, "submitted_by_user_id": None, "cleared_by_user_id": None,
    })
    store.packets[p["id"]] = p

    compute_projected(a)
    compute_readiness(p)
    return ok(ser_assignment(a), 201)


def _req_weekly(b, key):
    if key not in b:
        verr("Missing required field: %s" % key)
    v = b[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        verr("%s must be a number" % key)
    d = D(v)
    if d <= 0 or d > 84:
        verr("%s must be > 0 and <= 84" % key)
    return d


# ===========================================================================
# GET /assignments/{id}  and  GET /assignments
# ===========================================================================
@app.route("/assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    _uid, role = authenticate()
    authorize(role, READ_ROLES)
    a = store.assignments.get(aid)
    if not a:
        raise ApiError("ERR_ASSIGNMENT_NOT_FOUND", 404, "Assignment not found")
    return ok(ser_assignment(a), 200)


@app.route("/assignments", methods=["GET"])
def list_assignments():
    _uid, role = authenticate()
    authorize(role, READ_ROLES)
    limit, offset = pagination()
    rows = list(store.assignments.values())
    for f in ("clinician_id", "facility_id", "covering_license_id",
              "staffing_status", "compliance_status"):
        v = _filter(f)
        if v is not None:
            rows = [a for a in rows if a[f] == v]
    window, total = paginate(rows, limit, offset)
    return ok_list([ser_assignment(a) for a in window], limit, offset, total)


# ===========================================================================
# POST /assignments/{id}/activate
# ===========================================================================
@app.route("/assignments/<aid>/activate", methods=["POST"])
def activate_assignment(aid):
    _uid, role = authenticate()
    authorize(role, ["Recruiter"])
    a = store.assignments.get(aid)
    if not a:
        raise ApiError("ERR_ASSIGNMENT_NOT_FOUND", 404, "Assignment not found")
    # state gate (priority 7)
    if a["staffing_status"] not in ("DRAFT", "PENDING_START"):
        raise ApiError("ERR_INVALID_TRANSITION", 409, "Assignment cannot be activated")
    packet = _packet_of(aid)
    compute_readiness(packet)
    # packet-cleared gate (priority 11) — FULL_TERM basis
    if packet["status"] != "CLEARED" or packet["blocking_item_count_full_term_basis"] != 0:
        raise ApiError("ERR_PACKET_NOT_CLEARED", 422, "Credential packet not cleared for full term")
    # coverage gate (priority 12)
    covering = license_coverage(a, a["end_date"])
    if covering is None:
        raise ApiError("ERR_LICENSE_COVERAGE_MISSING", 422, "No covering license")
    # contract-executed gate (priority 13)
    contract = _contract_of(aid)
    if not contract or contract["status"] != "FULLY_EXECUTED":
        raise ApiError("ERR_CONTRACT_NOT_EXECUTED", 422, "Contract not fully executed")

    a["staffing_status"] = "ACTIVE"
    a["covering_license_id"] = covering
    touch(a)
    return ok(ser_assignment(a), 200)


def _packet_of(aid):
    for p in store.packets.values():
        if p["assignment_id"] == aid:
            return p
    return None


# ===========================================================================
# POST /assignments/{id}/cancel
# ===========================================================================
@app.route("/assignments/<aid>/cancel", methods=["POST"])
def cancel_assignment(aid):
    uid, role = authenticate()
    authorize(role, ["FacilityManager"])
    a = store.assignments.get(aid)
    if not a:
        raise ApiError("ERR_ASSIGNMENT_NOT_FOUND", 404, "Assignment not found")
    check_ownership(role, uid, a)
    b = body()
    effective_date = req_date(b, "effective_date")
    reason = req_str(b, "cancellation_reason")
    # state gate (priority 7)
    if a["staffing_status"] not in ("DRAFT", "PENDING_START", "ACTIVE"):
        raise ApiError("ERR_INVALID_TRANSITION", 409, "Assignment cannot be cancelled")
    # effective_date must be on/after clock date
    clock_date = store.clock_date().isoformat()
    if not date_le(clock_date, effective_date):
        verr("effective_date must be on or after the current clock date")
    perform_cancellation(a, effective_date, reason)
    return ok(ser_assignment(a), 200)


# ===========================================================================
# GET /assignments/{id}/contracts
# ===========================================================================
@app.route("/assignments/<aid>/contracts", methods=["GET"])
def list_assignment_contracts(aid):
    _uid, role = authenticate()
    authorize(role, READ_ROLES)
    if aid not in store.assignments:
        raise ApiError("ERR_ASSIGNMENT_NOT_FOUND", 404, "Assignment not found")
    limit, offset = pagination()
    rows = [c for c in store.contracts.values() if c["assignment_id"] == aid]
    window, total = paginate(rows, limit, offset)
    return ok_list([ser_contract(c) for c in window], limit, offset, total)


# ===========================================================================
# POST /contracts/{id}/transition
# ===========================================================================
CONTRACT_STATES = {"DRAFT", "SENT_FOR_SIGNATURE", "COUNTERSIGN_REQUESTED",
                   "FULLY_EXECUTED", "VOIDED"}


@app.route("/contracts/<cid>/transition", methods=["POST"])
def transition_contract(cid):
    uid, role = authenticate()
    authorize(role, ["Recruiter", "Clinician"])
    b = body()
    to = b.get("to")
    fine_authz("contract", role, to)
    contract = store.contracts.get(cid)
    if not contract:
        raise ApiError("ERR_CONTRACT_NOT_FOUND", 404, "Contract not found")
    a = store.assignments[contract["assignment_id"]]
    check_ownership(role, uid, a)
    to = req_str(b, "to")
    if to not in CONTRACT_STATES:
        verr("to must be one of %s" % sorted(CONTRACT_STATES))
    status = contract["status"]

    if to == "SENT_FOR_SIGNATURE":
        if status != "DRAFT":
            raise ApiError("ERR_INVALID_TRANSITION", 409, "Illegal contract transition")
        contract["status"] = "SENT_FOR_SIGNATURE"
        touch(contract)
    elif to == "COUNTERSIGN_REQUESTED":
        if status != "SENT_FOR_SIGNATURE":
            raise ApiError("ERR_INVALID_TRANSITION", 409, "Illegal contract transition")
        contract["status"] = "COUNTERSIGN_REQUESTED"
        note = b.get("countersign_note")
        if note is not None and not isinstance(note, str):
            verr("countersign_note must be a string")
        contract["countersign_note"] = note
        touch(contract)
    elif to == "FULLY_EXECUTED":
        if status != "SENT_FOR_SIGNATURE":
            raise ApiError("ERR_INVALID_TRANSITION", 409, "Illegal contract transition")
        # margin floor (priority 21), exact integer arithmetic
        if a["projected_margin_cents"] * 100 < a["projected_gross_bill_cents"] * 22:
            raise ApiError("ERR_MARGIN_BELOW_FLOOR", 422, "Projected margin below floor")
        contract["status"] = "FULLY_EXECUTED"
        contract["clinician_signed_at"] = store.now_ts()
        touch(contract)
        a["staffing_status"] = "PENDING_START"
        touch(a)
        clinician = store.clinicians[a["clinician_id"]]
        apply_clinician_recompute(clinician)
    else:
        raise ApiError("ERR_INVALID_TRANSITION", 409, "Illegal contract transition")
    return ok(ser_contract(contract), 200)


# ===========================================================================
# POST /contracts/{id}/revise
# ===========================================================================
@app.route("/contracts/<cid>/revise", methods=["POST"])
def revise_contract(cid):
    _uid, role = authenticate()
    authorize(role, ["Recruiter"])
    contract = store.contracts.get(cid)
    if not contract:
        raise ApiError("ERR_CONTRACT_NOT_FOUND", 404, "Contract not found")
    b = body()
    expected = req_int(b, "expected_contract_version")
    term_weeks = req_int(b, "term_weeks")
    if term_weeks < 1 or term_weeks > MAX_TERM_WEEKS:
        verr("term_weeks must be between 1 and 26")
    weekly = _req_weekly(b, "weekly_guaranteed_hours")
    base_pay = req_int(b, "base_pay_rate_cents_per_hour")
    bill_rate = req_int(b, "bill_rate_cents_per_hour")
    # state (priority 7)
    if contract["status"] not in ("DRAFT", "COUNTERSIGN_REQUESTED"):
        raise ApiError("ERR_INVALID_TRANSITION", 409, "Contract not revisable")
    # OCC (priority 8)
    if expected != contract["version"]:
        raise ApiError("ERR_STALE_CONTRACT_VERSION", 412, "Stale contract version")

    contract["term_weeks"] = term_weeks
    contract["weekly_guaranteed_hours"] = D(weekly)
    contract["base_pay_rate_cents_per_hour"] = base_pay
    contract["bill_rate_cents_per_hour"] = bill_rate
    contract["status"] = "DRAFT"
    contract["revision_count"] += 1
    touch(contract)

    a = store.assignments[contract["assignment_id"]]
    a["term_weeks"] = term_weeks
    recompute_end_date(a)
    total = D(weekly) * term_weeks
    a["guaranteed_hours_total"] = total
    a["guaranteed_hours_remaining"] = total - a["guaranteed_hours_consumed"] - a["guaranteed_hours_waived"]
    compute_projected(a)
    touch(a)
    return ok(ser_contract(contract), 200)


# ===========================================================================
# GET /assignments/{id}/extensions  and  POST /assignments/{id}/extensions
# ===========================================================================
@app.route("/assignments/<aid>/extensions", methods=["GET"])
def list_assignment_extensions(aid):
    _uid, role = authenticate()
    authorize(role, READ_ROLES)
    if aid not in store.assignments:
        raise ApiError("ERR_ASSIGNMENT_NOT_FOUND", 404, "Assignment not found")
    limit, offset = pagination()
    rows = [e for e in store.extensions.values() if e["assignment_id"] == aid]
    status_f = _filter("status")
    if status_f is not None:
        rows = [e for e in rows if e["status"] == status_f]
    window, total = paginate(rows, limit, offset)
    return ok_list([ser_extension(e) for e in window], limit, offset, total)


@app.route("/assignments/<aid>/extensions", methods=["POST"])
def open_extension(aid):
    uid, role = authenticate()
    authorize(role, ["Recruiter", "Clinician"])
    a = store.assignments.get(aid)
    if not a:
        raise ApiError("ERR_ASSIGNMENT_NOT_FOUND", 404, "Assignment not found")
    check_ownership(role, uid, a)
    b = body()
    expected = req_int(b, "expected_assignment_version")
    add_weeks = req_int(b, "proposed_additional_weeks")
    if add_weeks < 1:
        verr("proposed_additional_weeks must be >= 1")
    pay_rate = req_int(b, "proposed_pay_rate_cents_per_hour")
    bill_rate = req_int(b, "proposed_bill_rate_cents_per_hour")
    # OCC (priority 8)
    if expected != a["version"]:
        raise ApiError("ERR_STALE_ASSIGNMENT_VERSION", 412, "Stale assignment version")
    # compliance suspended (priority 10)
    if a["compliance_status"] == "SUSPENDED":
        raise ApiError("ERR_COMPLIANCE_SUSPENDED", 409, "Assignment compliance suspended")

    withdraw_open_extensions(a)
    ext = new_common(True)
    ext["id"] = _uuid()
    ext.update({
        "assignment_id": aid, "status": "PROPOSED",
        "proposed_additional_weeks": add_weeks,
        "proposed_pay_rate_cents_per_hour": pay_rate,
        "proposed_bill_rate_cents_per_hour": bill_rate,
        "round_count": 1, "initiated_by_role": role, "last_actor_role": role,
        "resolved_at": None,
    })
    store.extensions[ext["id"]] = ext
    touch(a)
    return ok(ser_extension(ext), 201)


# ===========================================================================
# POST /extension-requests/{id}/respond
# ===========================================================================
@app.route("/extension-requests/<eid>/respond", methods=["POST"])
def respond_extension(eid):
    uid, role = authenticate()
    authorize(role, ["Recruiter", "Clinician"])
    ext = store.extensions.get(eid)
    if not ext:
        raise ApiError("ERR_EXTENSION_NOT_FOUND", 404, "Extension request not found")
    a = store.assignments[ext["assignment_id"]]
    check_ownership(role, uid, a)
    b = body()
    action = req_enum(b, "action", {"COUNTER", "ACCEPT", "DECLINE"})

    # shape for COUNTER counter-terms (priority 5)
    if action == "COUNTER":
        add_weeks = req_int(b, "proposed_additional_weeks")
        if add_weeks < 1:
            verr("proposed_additional_weeks must be >= 1")
        pay_rate = req_int(b, "proposed_pay_rate_cents_per_hour")
        bill_rate = req_int(b, "proposed_bill_rate_cents_per_hour")

    # state (priority 7): open negotiation admits a response
    if ext["status"] not in ("PROPOSED", "COUNTERED"):
        raise ApiError("ERR_INVALID_TRANSITION", 409, "Extension not open")

    # SoD (priority 9)
    if role == ext["last_actor_role"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403, "Same role may not respond twice in a row")

    if action == "COUNTER":
        # rounds limit (priority 20)
        if ext["round_count"] >= 3:
            raise ApiError("ERR_NEGOTIATION_ROUNDS_EXHAUSTED", 409, "Negotiation rounds exhausted")
        ext["status"] = "COUNTERED" if ext["status"] == "PROPOSED" else "PROPOSED"
        ext["proposed_additional_weeks"] = add_weeks
        ext["proposed_pay_rate_cents_per_hour"] = pay_rate
        ext["proposed_bill_rate_cents_per_hour"] = bill_rate
        ext["round_count"] += 1
        ext["last_actor_role"] = role
        touch(ext)
    elif action == "DECLINE":
        ext["status"] = "DECLINED"
        ext["resolved_at"] = store.now_ts()
        ext["last_actor_role"] = role
        touch(ext)
    else:  # ACCEPT
        if a["staffing_status"] not in ("PENDING_START", "ACTIVE"):
            raise ApiError("ERR_INVALID_TRANSITION", 409, "Assignment not open for extension")
        new_term = a["term_weeks"] + ext["proposed_additional_weeks"]
        new_end = add_days(a["start_date"], new_term * 7 - 1)
        # coverage (priority 12)
        probe = {"clinician_id": a["clinician_id"], "facility_id": a["facility_id"],
                 "required_license_type": a["required_license_type"]}
        if license_coverage(probe, new_end) is None:
            raise ApiError("ERR_LICENSE_COVERAGE_MISSING", 422, "No covering license for new term")
        # term limit (priority 19)
        if new_term > MAX_TERM_WEEKS:
            raise ApiError("ERR_TERM_LIMIT_EXCEEDED", 422, "Term limit exceeded")
        ext["status"] = "ACCEPTED"
        ext["resolved_at"] = store.now_ts()
        ext["last_actor_role"] = role
        touch(ext)
        accept_extension(ext, a)
    return ok(ser_extension(ext), 200)
