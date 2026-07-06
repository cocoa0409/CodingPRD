from flask import Blueprint, request
from db import db
from errors import err
from middleware import require
from response import ok, created, listing, paginate, apply_pagination
from common import (get_body, base_fields, touch, public, find_or_404,
                    require_str, opt_str, require_int, opt_int, require_number,
                    opt_number, require_enum, opt_bool, require_datetime)
from timeutil import parse_iso
import services as S

bp = Blueprint("training", __name__)

CATEGORIES = {"LEADERSHIP", "TECHNICAL", "COMPLIANCE", "SALES"}
DELIVERY_MODES = {"VIRTUAL", "ONSITE", "HYBRID"}
PRICING_MODELS = {"PER_SEAT", "FLAT"}

ALL_ROLES = ["ProgramDesigner", "SchedulingCoordinator", "Facilitator", "Learner", "FinanceManager"]


def now_dt():
    return parse_iso(db.logical_clock)


# All persistent resource tables, for global existence checks (PRD §2.9 step 3 vs 4):
# an id that resolves to *some* existing resource passes the existence check; a
# resolved id of the wrong type for a foreign-key slot is a wrong-type reference.
def _exists_anywhere(rid):
    for table in (db.programs, db.program_versions, db.facilitators, db.cohorts,
                  db.sessions, db.session_assignments, db.registrations,
                  db.assessments, db.certificates, db.contracts, db.invoices,
                  db.evaluations):
        if rid in table:
            return True
    return False


def out(rec):
    return public(rec)


def list_response(table_values, filters, query_args):
    """Generic filtered+paginated list. filters: list of (field, value-or-None)."""
    limit, offset = paginate(query_args)
    items = list(table_values)
    for field, val in filters:
        if val is not None:
            items = [r for r in items if r.get(field) == val]
    pub = [public(r) for r in items]
    page, total = apply_pagination(pub, limit, offset)
    return listing(page, limit, offset, total)


# =============================================================================
# Clock
# =============================================================================
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require(["SchedulingCoordinator", "FinanceManager", "ProgramDesigner"])
    body = get_body()
    val = require_datetime(body, "to_iso8601")
    db.logical_clock = val
    return ok({})


# =============================================================================
# Program
# =============================================================================
@bp.route("/programs", methods=["POST"])
def create_program():
    require(["ProgramDesigner"])
    body = get_body()
    title = require_str(body, "title")
    category = require_enum(body, "category", CATEGORIES)
    delivery_mode = require_enum(body, "delivery_mode", DELIVERY_MODES)
    ceu = opt_number(body, "ceu_credits", 0)
    if ceu < 0 or ceu > 40:
        raise err("ERR_INVALID_REQUEST", "ceu_credits out of range 0..40")
    is_custom = opt_bool(body, "is_custom", False)
    rec = base_fields()
    rec.update({
        "title": title, "category": category, "delivery_mode": delivery_mode,
        "ceu_credits": ceu, "is_custom": is_custom,
        "status": "DRAFT", "active_version_id": None,
    })
    db.programs[rec["id"]] = rec
    return created(out(rec))


@bp.route("/programs/<pid>", methods=["GET"])
def get_program(pid):
    require(ALL_ROLES)
    rec = find_or_404(db.programs, pid)
    return ok(out(rec))


@bp.route("/programs", methods=["GET"])
def list_programs():
    require(ALL_ROLES)
    a = request.args
    return list_response(db.programs.values(),
                         [("category", a.get("category")), ("status", a.get("status"))], a)


@bp.route("/programs/<pid>/retire", methods=["POST"])
def retire_program(pid):
    require(["ProgramDesigner"])
    rec = find_or_404(db.programs, pid)
    rec["status"] = "RETIRED"
    touch(rec)
    return ok(out(rec))


# =============================================================================
# ProgramVersion
# =============================================================================
@bp.route("/program-versions", methods=["POST"])
def create_pv():
    require(["ProgramDesigner"])
    body = get_body()
    program_id = require_str(body, "program_id")
    version_label = require_str(body, "version_label")
    duration_hours = require_number(body, "duration_hours")
    if duration_hours <= 0:
        raise err("ERR_INVALID_REQUEST", "duration_hours must be > 0")
    pricing_model = require_enum(body, "pricing_model", PRICING_MODELS)
    per_seat = opt_int(body, "per_seat_cents", 0)
    flat = opt_int(body, "flat_fee_cents", 0)
    materials = opt_int(body, "materials_kit_cents", 0)
    min_seats = opt_int(body, "min_seats", 1)
    if min_seats < 1:
        raise err("ERR_INVALID_REQUEST", "min_seats must be >= 1")
    pass_threshold = opt_int(body, "pass_threshold_pct", 70)
    if pass_threshold < 0 or pass_threshold > 100:
        raise err("ERR_INVALID_REQUEST", "pass_threshold_pct out of range")
    # existence then reference type
    prog = db.programs.get(program_id)
    if prog is None:
        raise err("ERR_NOT_FOUND", "program_id not found")
    rec = base_fields()
    rec.update({
        "program_id": program_id, "version_label": version_label,
        "duration_hours": duration_hours, "pricing_model": pricing_model,
        "per_seat_cents": per_seat, "flat_fee_cents": flat,
        "materials_kit_cents": materials, "min_seats": min_seats,
        "pass_threshold_pct": pass_threshold, "status": "DRAFT",
    })
    db.program_versions[rec["id"]] = rec
    return created(out(rec))


@bp.route("/program-versions/<vid>", methods=["GET"])
def get_pv(vid):
    require(ALL_ROLES)
    return ok(out(find_or_404(db.program_versions, vid)))


@bp.route("/program-versions", methods=["GET"])
def list_pv():
    require(ALL_ROLES)
    a = request.args
    return list_response(db.program_versions.values(),
                         [("program_id", a.get("program_id")), ("status", a.get("status"))], a)


@bp.route("/program-versions/<vid>/submit", methods=["POST"])
def submit_pv(vid):
    require(["ProgramDesigner"])
    pv = find_or_404(db.program_versions, vid)
    if pv["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Version not in DRAFT")
    if pv["duration_hours"] <= 0:
        raise err("ERR_PRICING_INCOMPLETE", "duration_hours must be > 0")
    if pv["pricing_model"] == "PER_SEAT" and pv["per_seat_cents"] <= 0:
        raise err("ERR_PRICING_INCOMPLETE", "per_seat_cents must be > 0")
    if pv["pricing_model"] == "FLAT" and pv["flat_fee_cents"] <= 0:
        raise err("ERR_PRICING_INCOMPLETE", "flat_fee_cents must be > 0")
    pv["status"] = "IN_REVIEW"
    touch(pv)
    return ok(out(pv))


@bp.route("/program-versions/<vid>/request-changes", methods=["POST"])
def request_changes_pv(vid):
    require(["ProgramDesigner"])
    pv = find_or_404(db.program_versions, vid)
    if pv["status"] != "IN_REVIEW":
        raise err("ERR_INVALID_STATE", "Version not in IN_REVIEW")
    pv["status"] = "DRAFT"
    touch(pv)
    return ok(out(pv))


@bp.route("/program-versions/<vid>/approve", methods=["POST"])
def approve_pv(vid):
    require(["ProgramDesigner"])
    pv = find_or_404(db.program_versions, vid)
    if pv["status"] != "IN_REVIEW":
        raise err("ERR_INVALID_STATE", "Version not in IN_REVIEW")
    prog = db.programs.get(pv["program_id"])
    if prog and prog["status"] == "RETIRED":
        raise err("ERR_PROGRAM_RETIRED", "Cannot approve a version of a retired program")
    # supersede prior approved
    for other in db.program_versions.values():
        if (other["id"] != pv["id"] and other["program_id"] == pv["program_id"]
                and other["status"] == "APPROVED"):
            other["status"] = "SUPERSEDED"
            touch(other)
    pv["status"] = "APPROVED"
    touch(pv)
    if prog:
        prog["active_version_id"] = pv["id"]
        if prog["status"] == "DRAFT":
            prog["status"] = "PUBLISHED"
        touch(prog)
    return ok(out(pv))


# =============================================================================
# Facilitator
# =============================================================================
@bp.route("/facilitators", methods=["POST"])
def create_facilitator():
    require(["SchedulingCoordinator"])
    body = get_body()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    if "certified_categories" not in body or not isinstance(body["certified_categories"], list):
        raise err("ERR_INVALID_REQUEST", "certified_categories must be an array")
    cats = body["certified_categories"]
    for c in cats:
        if c not in CATEGORIES:
            raise err("ERR_INVALID_REQUEST", "invalid category in certified_categories")
    travel = opt_int(body, "travel_base_cents", 0)
    # unique email
    for f in db.facilitators.values():
        if f["email"] == email:
            raise err("ERR_INVALID_REQUEST", "email already in use")
    rec = base_fields()
    rec.update({
        "full_name": full_name, "email": email, "certified_categories": cats,
        "travel_base_cents": travel, "status": "ACTIVE",
    })
    db.facilitators[rec["id"]] = rec
    return created(out(rec))


@bp.route("/facilitators/<fid>", methods=["GET"])
def get_facilitator(fid):
    require(ALL_ROLES)
    return ok(out(find_or_404(db.facilitators, fid)))


@bp.route("/facilitators", methods=["GET"])
def list_facilitators():
    require(ALL_ROLES)
    a = request.args
    return list_response(db.facilitators.values(), [("status", a.get("status"))], a)


@bp.route("/facilitators/<fid>/suspend", methods=["POST"])
def suspend_facilitator(fid):
    require(["SchedulingCoordinator"])
    f = find_or_404(db.facilitators, fid)
    f["status"] = "SUSPENDED"
    touch(f)
    return ok(out(f))


# =============================================================================
# EnterpriseContract
# =============================================================================
@bp.route("/contracts", methods=["POST"])
def create_contract():
    require(["FinanceManager"])
    body = get_body()
    client_name = require_str(body, "client_name")
    budget = require_int(body, "budget_cents")
    if budget < 0:
        raise err("ERR_INVALID_REQUEST", "budget_cents must be >= 0")
    is_recurring = opt_bool(body, "is_recurring", False)
    rec = base_fields()
    rec.update({
        "client_name": client_name, "budget_cents": budget,
        "committed_cents": 0, "remaining_cents": budget,
        "is_recurring": is_recurring, "status": "ACTIVE",
    })
    db.contracts[rec["id"]] = rec
    return created(out(rec))


@bp.route("/contracts/<cid>", methods=["GET"])
def get_contract(cid):
    require(ALL_ROLES)
    return ok(out(find_or_404(db.contracts, cid)))


@bp.route("/contracts", methods=["GET"])
def list_contracts():
    require(ALL_ROLES)
    a = request.args
    return list_response(db.contracts.values(), [("status", a.get("status"))], a)


@bp.route("/contracts/<cid>/close", methods=["POST"])
def close_contract(cid):
    require(["FinanceManager"])
    c = find_or_404(db.contracts, cid)
    if c["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Contract not ACTIVE")
    blocking = {"OPEN", "LOCKED", "RUNNING", "DELIVERED"}
    for co in db.cohorts.values():
        if co.get("contract_id") == cid and co["status"] in blocking:
            raise err("ERR_CONTRACT_HAS_OPEN_COHORTS", "Contract has active cohorts")
    c["status"] = "CLOSED"
    touch(c)
    return ok(out(c))


# =============================================================================
# Cohort
# =============================================================================
@bp.route("/cohorts", methods=["POST"])
def create_cohort():
    require(["SchedulingCoordinator"])
    body = get_body()
    program_version_id = require_str(body, "program_version_id")
    lead_facilitator_id = require_str(body, "lead_facilitator_id")
    contract_id = opt_str(body, "contract_id", None)
    seat_capacity = require_int(body, "seat_capacity")
    if seat_capacity < 1:
        raise err("ERR_INVALID_REQUEST", "seat_capacity must be >= 1")
    waitlist_capacity = opt_int(body, "waitlist_capacity", 0)
    if waitlist_capacity < 0:
        raise err("ERR_INVALID_REQUEST", "waitlist_capacity must be >= 0")
    delivery_mode = require_enum(body, "delivery_mode", DELIVERY_MODES)
    starts_at = require_datetime(body, "starts_at")
    ends_at = require_datetime(body, "ends_at")
    enroll_deadline = require_datetime(body, "enroll_deadline")
    if parse_iso(ends_at) <= parse_iso(starts_at):
        raise err("ERR_INVALID_REQUEST", "ends_at must be after starts_at")
    if parse_iso(enroll_deadline) > parse_iso(starts_at):
        raise err("ERR_INVALID_REQUEST", "enroll_deadline must be <= starts_at")
    # PRD §2.9 step 3: existence verified left-to-right across every referenced id;
    # the first id that does not resolve to ANY existing resource -> ERR_NOT_FOUND.
    if not _exists_anywhere(program_version_id):
        raise err("ERR_NOT_FOUND", "program_version_id not found")
    if not _exists_anywhere(lead_facilitator_id):
        raise err("ERR_NOT_FOUND", "lead_facilitator_id not found")
    if contract_id is not None and not _exists_anywhere(contract_id):
        raise err("ERR_NOT_FOUND", "contract_id not found")
    # PRD §2.9 step 4: each foreign key must reference a resource of the correct
    # type; a wrong-type (or wrong-lifecycle) reference -> ERR_INVALID_REFERENCE.
    pv = db.program_versions.get(program_version_id)
    if pv is None:
        raise err("ERR_INVALID_REFERENCE", "program_version_id must reference a ProgramVersion")
    fac = db.facilitators.get(lead_facilitator_id)
    if fac is None:
        raise err("ERR_INVALID_REFERENCE", "lead_facilitator_id must reference a Facilitator")
    if contract_id is not None and db.contracts.get(contract_id) is None:
        raise err("ERR_INVALID_REFERENCE", "contract_id must reference a Contract")
    rec = base_fields()
    rec.update({
        "program_version_id": program_version_id,
        "lead_facilitator_id": lead_facilitator_id,
        "contract_id": contract_id,
        "seat_capacity": seat_capacity,
        "waitlist_capacity": waitlist_capacity,
        "delivery_mode": delivery_mode,
        "starts_at": starts_at, "ends_at": ends_at, "enroll_deadline": enroll_deadline,
        "seats_reserved": 0, "seats_confirmed": 0, "seats_waitlisted": 0,
        "nps_score": None, "status": "SCHEDULED",
        "_reserved_cents": 0,
    })
    db.cohorts[rec["id"]] = rec
    return created(out(rec))


@bp.route("/cohorts/<cid>", methods=["GET"])
def get_cohort(cid):
    require(ALL_ROLES)
    return ok(out(find_or_404(db.cohorts, cid)))


@bp.route("/cohorts", methods=["GET"])
def list_cohorts():
    require(ALL_ROLES)
    a = request.args
    return list_response(db.cohorts.values(), [
        ("contract_id", a.get("contract_id")),
        ("lead_facilitator_id", a.get("lead_facilitator_id")),
        ("program_version_id", a.get("program_version_id")),
        ("status", a.get("status")),
    ], a)


@bp.route("/cohorts/<cid>/open", methods=["POST"])
def open_cohort(cid):
    require(["SchedulingCoordinator"])
    co = find_or_404(db.cohorts, cid)
    if co["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Cohort not SCHEDULED")
    pv = db.program_versions.get(co["program_version_id"])
    if pv is None or pv["status"] != "APPROVED":
        raise err("ERR_VERSION_NOT_APPROVED", "Program version not APPROVED")
    prog = db.programs.get(pv["program_id"]) if pv else None
    fac = db.facilitators.get(co["lead_facilitator_id"])
    category = prog["category"] if prog else None
    if (fac is None or fac["status"] != "ACTIVE"
            or category not in fac["certified_categories"]):
        raise err("ERR_FACILITATOR_NOT_CERTIFIED", "Facilitator not certified or not active")
    # delivery mode compatibility
    prog_mode = prog["delivery_mode"] if prog else None
    if not _delivery_compatible(prog_mode, co["delivery_mode"]):
        raise err("ERR_DELIVERY_MODE_MISMATCH", "Delivery mode incompatible")
    if now_dt() >= parse_iso(co["enroll_deadline"]):
        raise err("ERR_ENROLL_WINDOW_CLOSED", "Enrollment window closed")
    co["status"] = "OPEN"
    touch(co)
    return ok(out(co))


def _delivery_compatible(program_mode, cohort_mode):
    if program_mode == "HYBRID":
        return True
    return program_mode == cohort_mode


@bp.route("/cohorts/<cid>/lock", methods=["POST"])
def lock_cohort(cid):
    require(["SchedulingCoordinator"])
    co = find_or_404(db.cohorts, cid)
    body = get_body()
    expected = require_int(body, "expected_cohort_version")
    if co["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Cohort not OPEN")
    # OCC before min-seats
    if expected != co["version"]:
        raise err("ERR_STALE_COHORT_VERSION", "expected_cohort_version mismatch")
    pv = db.program_versions.get(co["program_version_id"])
    if co["seats_confirmed"] < pv["min_seats"]:
        raise err("ERR_MIN_SEATS_NOT_MET", "Minimum seats not met")
    co["status"] = "LOCKED"
    touch(co)  # increments version by 1
    inv = S.create_invoice(co, "PROVISIONAL")
    if co.get("contract_id"):
        contract = db.contracts.get(co["contract_id"])
        if contract:
            co["_reserved_cents"] = inv["total_cents"]
    return ok(out(co))


@bp.route("/cohorts/<cid>/start", methods=["POST"])
def start_cohort(cid):
    require(["SchedulingCoordinator"])
    co = find_or_404(db.cohorts, cid)
    if co["status"] != "LOCKED":
        raise err("ERR_INVALID_STATE", "Cohort not LOCKED")
    if now_dt() < parse_iso(co["starts_at"]):
        raise err("ERR_BEFORE_START", "Clock before starts_at")
    co["status"] = "RUNNING"
    touch(co)
    return ok(out(co))


@bp.route("/cohorts/<cid>/deliver", methods=["POST"])
def deliver_cohort(cid):
    require(["SchedulingCoordinator"])
    co = find_or_404(db.cohorts, cid)
    if co["status"] != "RUNNING":
        raise err("ERR_INVALID_STATE", "Cohort not RUNNING")
    if now_dt() < parse_iso(co["ends_at"]):
        raise err("ERR_BEFORE_END", "Clock before ends_at")
    co["status"] = "DELIVERED"
    # settle attendance: CONFIRMED with no mark -> NO_SHOW
    for r in db.registrations.values():
        if r["cohort_id"] == cid and r["status"] == "CONFIRMED":
            r["status"] = "NO_SHOW"
            touch(r)
    S.recount_seats(co)
    touch(co)
    return ok(out(co))


@bp.route("/cohorts/<cid>/close", methods=["POST"])
def close_cohort(cid):
    require(["SchedulingCoordinator"])
    co = find_or_404(db.cohorts, cid)
    if co["status"] != "DELIVERED":
        raise err("ERR_INVALID_STATE", "Cohort not DELIVERED")
    S.close_cohort_settlement(co)  # may raise ERR_CONTRACT_BUDGET_EXCEEDED
    co["status"] = "CLOSED"
    touch(co)
    return ok(out(co))


@bp.route("/cohorts/<cid>/cancel", methods=["POST"])
def cancel_cohort(cid):
    require(["SchedulingCoordinator"])
    co = find_or_404(db.cohorts, cid)
    if co["status"] not in ("OPEN", "LOCKED"):
        raise err("ERR_INVALID_STATE", "Cohort not cancellable from current state")
    S.cancel_cohort_cascade(co)
    co["status"] = "CANCELLED"
    touch(co)
    return ok(out(co))


# =============================================================================
# Session
# =============================================================================
@bp.route("/cohorts/<cid>/sessions", methods=["POST"])
def create_session(cid):
    require(["SchedulingCoordinator"])
    co = find_or_404(db.cohorts, cid)
    body = get_body()
    title = require_str(body, "title")
    starts_at = require_datetime(body, "starts_at")
    ends_at = require_datetime(body, "ends_at")
    room_or_url = require_str(body, "room_or_url")
    s_start = parse_iso(starts_at)
    s_end = parse_iso(ends_at)
    if s_end <= s_start:
        raise err("ERR_INVALID_REQUEST", "ends_at must be after starts_at")
    # session within cohort window
    c_start = parse_iso(co["starts_at"])
    c_end = parse_iso(co["ends_at"])
    if s_start < c_start or s_end > c_end:
        raise err("ERR_SESSION_OUT_OF_RANGE", "Session outside cohort window")
    # room conflict: same room, closed interval (adjacency rejected)
    for other in db.sessions.values():
        if other["cohort_id"] == cid and other["room_or_url"] == room_or_url:
            o_start = parse_iso(other["starts_at"])
            o_end = parse_iso(other["ends_at"])
            # closed-interval overlap: not (s_end < o_start or s_start > o_end)
            if not (s_end < o_start or s_start > o_end):
                raise err("ERR_ROOM_CONFLICT", "Room conflict")
    rec = base_fields()
    rec.update({
        "cohort_id": cid, "title": title, "starts_at": starts_at,
        "ends_at": ends_at, "room_or_url": room_or_url, "status": "PLANNED",
    })
    db.sessions[rec["id"]] = rec
    return created(out(rec))


@bp.route("/cohorts/<cid>/sessions", methods=["GET"])
def list_cohort_sessions(cid):
    require(ALL_ROLES)
    find_or_404(db.cohorts, cid)
    a = request.args
    return list_response(db.sessions.values(), [("cohort_id", cid)], a)


@bp.route("/sessions/<sid>", methods=["GET"])
def get_session(sid):
    require(ALL_ROLES)
    return ok(out(find_or_404(db.sessions, sid)))


# =============================================================================
# SessionAssignment
# =============================================================================
@bp.route("/sessions/<sid>/assignments", methods=["POST"])
def create_assignment(sid):
    require(["SchedulingCoordinator"])
    sess = find_or_404(db.sessions, sid)
    body = get_body()
    facilitator_id = require_str(body, "facilitator_id")
    role = body.get("role", "ASSIST")
    if role not in ("LEAD", "ASSIST"):
        raise err("ERR_INVALID_REQUEST", "role must be LEAD or ASSIST")
    fac = db.facilitators.get(facilitator_id)
    if fac is None:
        raise err("ERR_NOT_FOUND", "facilitator_id not found")
    # double-booking: facilitator's ACTIVE assignments must not overlap (half-open)
    s_start = parse_iso(sess["starts_at"])
    s_end = parse_iso(sess["ends_at"])
    for other in db.session_assignments.values():
        if other["facilitator_id"] == facilitator_id and other["status"] == "ACTIVE":
            osess = db.sessions.get(other["session_id"])
            if osess is None:
                continue
            o_start = parse_iso(osess["starts_at"])
            o_end = parse_iso(osess["ends_at"])
            # half-open overlap: o_start < s_end and s_start < o_end
            if o_start < s_end and s_start < o_end:
                raise err("ERR_FACILITATOR_DOUBLE_BOOKED", "Facilitator double-booked")
    rec = base_fields()
    rec.update({
        "session_id": sid, "facilitator_id": facilitator_id,
        "role": role, "status": "ACTIVE",
    })
    db.session_assignments[rec["id"]] = rec
    return created(out(rec))


@bp.route("/sessions/<sid>/assignments", methods=["GET"])
def list_session_assignments(sid):
    require(ALL_ROLES)
    find_or_404(db.sessions, sid)
    a = request.args
    return list_response(db.session_assignments.values(), [("session_id", sid)], a)


@bp.route("/assignments", methods=["GET"])
def list_assignments():
    require(ALL_ROLES)
    a = request.args
    return list_response(db.session_assignments.values(), [
        ("facilitator_id", a.get("facilitator_id")),
        ("session_id", a.get("session_id")),
        ("status", a.get("status")),
    ], a)


# =============================================================================
# Registration
# =============================================================================
NON_TERMINAL_REG = {"WAITLISTED", "ENROLLED", "CONFIRMED"}


@bp.route("/cohorts/<cid>/registrations", methods=["POST"])
def create_registration(cid):
    require(["Learner", "SchedulingCoordinator"])
    co = find_or_404(db.cohorts, cid)
    body = get_body()
    learner_email = require_str(body, "learner_email")
    learner_name = require_str(body, "learner_name")
    # duplicate (non-terminal) email
    for r in db.registrations.values():
        if (r["cohort_id"] == cid and r["learner_email"] == learner_email
                and r["status"] in NON_TERMINAL_REG):
            raise err("ERR_DUPLICATE_REGISTRATION", "learner_email already registered")
    # enroll window
    if now_dt() >= parse_iso(co["enroll_deadline"]):
        raise err("ERR_ENROLL_WINDOW_CLOSED", "Enrollment window closed")
    contract_id = co.get("contract_id")
    billing_mode = "CONTRACT" if contract_id else "SELF_PAY"
    rec = base_fields()
    rec.update({
        "cohort_id": cid, "learner_email": learner_email, "learner_name": learner_name,
        "contract_id": contract_id, "billing_mode": billing_mode,
        "seat_price_cents": 0,
    })
    seats_used = co["seats_reserved"] + co["seats_confirmed"]
    if seats_used < co["seat_capacity"]:
        rec["status"] = "ENROLLED"
    else:
        # waitlist path
        if co["seats_waitlisted"] < co["waitlist_capacity"]:
            rec["status"] = "WAITLISTED"
        else:
            raise err("ERR_WAITLIST_FULL", "Seats full and waitlist at capacity")
    db.registrations[rec["id"]] = rec
    S.recount_seats(co)
    touch(co)
    return created(out(rec))


@bp.route("/cohorts/<cid>/registrations", methods=["GET"])
def list_cohort_registrations(cid):
    require(ALL_ROLES)
    find_or_404(db.cohorts, cid)
    a = request.args
    return list_response(db.registrations.values(), [("cohort_id", cid)], a)


@bp.route("/registrations/<rid>", methods=["GET"])
def get_registration(rid):
    require(ALL_ROLES)
    return ok(out(find_or_404(db.registrations, rid)))


@bp.route("/registrations", methods=["GET"])
def list_registrations():
    require(["SchedulingCoordinator", "FinanceManager"])
    a = request.args
    return list_response(db.registrations.values(), [
        ("contract_id", a.get("contract_id")),
        ("cohort_id", a.get("cohort_id")),
        ("status", a.get("status")),
    ], a)


@bp.route("/registrations/<rid>/confirm", methods=["POST"])
def confirm_registration(rid):
    require(["Learner"])
    r = find_or_404(db.registrations, rid)
    if r["status"] != "ENROLLED":
        raise err("ERR_INVALID_STATE", "Registration not ENROLLED")
    co = db.cohorts.get(r["cohort_id"])
    if co["status"] != "OPEN":
        raise err("ERR_COHORT_NOT_OPEN", "Cohort not OPEN")
    r["status"] = "CONFIRMED"
    # lock seat price
    pv = db.program_versions.get(co["program_version_id"])
    if pv["pricing_model"] == "PER_SEAT":
        r["seat_price_cents"] = pv["per_seat_cents"]
    else:
        r["seat_price_cents"] = 0
    touch(r)
    S.recount_seats(co)
    touch(co)
    return ok(out(r))


@bp.route("/registrations/<rid>/withdraw", methods=["POST"])
def withdraw_registration(rid):
    require(["Learner", "SchedulingCoordinator"])
    r = find_or_404(db.registrations, rid)
    if r["status"] not in ("ENROLLED", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "Registration not withdrawable")
    co = db.cohorts.get(r["cohort_id"])
    if co["status"] != "OPEN":
        raise err("ERR_COHORT_NOT_OPEN", "Cohort not OPEN")
    r["status"] = "WITHDRAWN"
    touch(r)
    S.recount_seats(co)
    touch(co)
    S.promote_waitlist(co)
    return ok(out(r))


@bp.route("/registrations/<rid>/mark-attendance", methods=["POST"])
def mark_attendance(rid):
    require(["Facilitator"])
    r = find_or_404(db.registrations, rid)
    if r["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Registration not CONFIRMED")
    co = db.cohorts.get(r["cohort_id"])
    if co["status"] not in ("RUNNING", "DELIVERED"):
        raise err("ERR_COHORT_NOT_RUNNING", "Cohort not RUNNING/DELIVERED")
    r["status"] = "ATTENDED"
    touch(r)
    S.recount_seats(co)
    touch(co)
    return ok(out(r))


# =============================================================================
# Assessment
# =============================================================================
@bp.route("/registrations/<rid>/assessments", methods=["POST"])
def create_assessment(rid):
    require(["Facilitator"])
    r = find_or_404(db.registrations, rid)
    body = get_body()
    raw_score = require_int(body, "raw_score")
    max_score = require_int(body, "max_score")
    if raw_score < 0:
        raise err("ERR_INVALID_REQUEST", "raw_score must be >= 0")
    if max_score < 1:
        raise err("ERR_INVALID_REQUEST", "max_score must be >= 1")
    co = db.cohorts.get(r["cohort_id"])
    pv = db.program_versions.get(co["program_version_id"])
    pct, outcome = S.assessment_percent_and_outcome(raw_score, max_score, pv["pass_threshold_pct"])
    rec = base_fields()
    rec.update({
        "registration_id": rid, "raw_score": raw_score, "max_score": max_score,
        "percent_score": pct, "outcome": outcome, "status": "GRADED",
    })
    db.assessments[rec["id"]] = rec
    return created(out(rec))


@bp.route("/registrations/<rid>/assessments", methods=["GET"])
def list_reg_assessments(rid):
    require(ALL_ROLES)
    find_or_404(db.registrations, rid)
    a = request.args
    return list_response(db.assessments.values(), [("registration_id", rid)], a)


@bp.route("/assessments/<aid>", methods=["GET"])
def get_assessment(aid):
    require(ALL_ROLES)
    return ok(out(find_or_404(db.assessments, aid)))


@bp.route("/assessments/<aid>/void", methods=["POST"])
def void_assessment(aid):
    require(["ProgramDesigner", "Facilitator"])
    a = find_or_404(db.assessments, aid)
    if a["status"] != "GRADED":
        raise err("ERR_INVALID_STATE", "Assessment not GRADED")
    a["status"] = "VOIDED"
    touch(a)
    return ok(out(a))


# =============================================================================
# Certificate
# =============================================================================
@bp.route("/registrations/<rid>/certificate", methods=["POST"])
def issue_certificate(rid):
    require(["ProgramDesigner", "SchedulingCoordinator"])
    r = find_or_404(db.registrations, rid)
    body = get_body()
    assessment_id = require_str(body, "assessment_id")
    a = db.assessments.get(assessment_id)
    if a is None:
        raise err("ERR_NOT_FOUND", "assessment_id not found")
    if a["registration_id"] != rid:
        raise err("ERR_INVALID_REFERENCE", "assessment does not belong to registration")
    if r["status"] != "ATTENDED" or a["outcome"] != "PASS":
        raise err("ERR_NOT_ELIGIBLE_FOR_CERTIFICATE", "Not eligible for certificate")
    co = db.cohorts.get(r["cohort_id"])
    pv = db.program_versions.get(co["program_version_id"])
    prog = db.programs.get(pv["program_id"]) if pv else None
    ceu = prog["ceu_credits"] if prog else 0
    # monotone serial within cohort
    existing = [c for c in db.certificates.values()
                if db.registrations.get(c["registration_id"], {}).get("cohort_id") == co["id"]]
    serial_num = len(existing) + 1
    rec = base_fields()
    rec.update({
        "registration_id": rid, "assessment_id": assessment_id,
        "ceu_awarded": ceu, "serial": "CERT-%s-%04d" % (co["id"][:8], serial_num),
        "status": "ISSUED",
    })
    db.certificates[rec["id"]] = rec
    return created(out(rec))


@bp.route("/registrations/<rid>/certificates", methods=["GET"])
def list_reg_certificates(rid):
    require(ALL_ROLES)
    find_or_404(db.registrations, rid)
    a = request.args
    return list_response(db.certificates.values(), [("registration_id", rid)], a)


@bp.route("/certificates/<certid>", methods=["GET"])
def get_certificate(certid):
    require(ALL_ROLES)
    return ok(out(find_or_404(db.certificates, certid)))


@bp.route("/certificates", methods=["GET"])
def list_certificates():
    require(ALL_ROLES)
    a = request.args
    return list_response(db.certificates.values(), [
        ("assessment_id", a.get("assessment_id")),
        ("registration_id", a.get("registration_id")),
        ("status", a.get("status")),
    ], a)


@bp.route("/certificates/<certid>/revoke", methods=["POST"])
def revoke_certificate(certid):
    require(["ProgramDesigner"])
    cert = find_or_404(db.certificates, certid)
    if cert["status"] != "ISSUED":
        raise err("ERR_INVALID_STATE", "Certificate not ISSUED")
    r = db.registrations.get(cert["registration_id"])
    a = db.assessments.get(cert["assessment_id"])
    reg_attended = r is not None and r["status"] == "ATTENDED"
    assess_voided = a is not None and a["status"] == "VOIDED"
    # permitted only when registration not ATTENDED OR assessment VOIDED
    if reg_attended and not assess_voided:
        raise err("ERR_CERTIFICATE_STILL_VALID", "Certificate still valid")
    cert["status"] = "REVOKED"
    cert["ceu_awarded"] = 0
    touch(cert)
    return ok(out(cert))


# =============================================================================
# Invoice (read-only)
# =============================================================================
@bp.route("/cohorts/<cid>/invoices", methods=["GET"])
def list_cohort_invoices(cid):
    require(ALL_ROLES)
    find_or_404(db.cohorts, cid)
    a = request.args
    return list_response(db.invoices.values(), [("cohort_id", cid)], a)


@bp.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    require(ALL_ROLES)
    return ok(out(find_or_404(db.invoices, iid)))


@bp.route("/invoices", methods=["GET"])
def list_invoices():
    require(ALL_ROLES)
    a = request.args
    return list_response(db.invoices.values(), [
        ("contract_id", a.get("contract_id")),
        ("cohort_id", a.get("cohort_id")),
        ("status", a.get("status")),
    ], a)


# =============================================================================
# Evaluation
# =============================================================================
@bp.route("/registrations/<rid>/evaluation", methods=["POST"])
def create_evaluation(rid):
    require(["Learner"])
    r = find_or_404(db.registrations, rid)
    body = get_body()
    nps_rating = require_int(body, "nps_rating")
    if nps_rating < 0 or nps_rating > 10:
        raise err("ERR_INVALID_REQUEST", "nps_rating must be 0..10")
    comment = opt_str(body, "comment", "")
    co = db.cohorts.get(r["cohort_id"])
    if r["status"] not in ("ATTENDED", "NO_SHOW") or co["status"] not in ("DELIVERED", "CLOSED"):
        raise err("ERR_EVALUATION_NOT_ALLOWED", "Evaluation not allowed")
    rec = base_fields(with_common=False)
    rec.update({
        "registration_id": rid, "cohort_id": r["cohort_id"],
        "nps_rating": nps_rating, "comment": comment,
    })
    db.evaluations[rec["id"]] = rec
    return created(out(rec))


@bp.route("/registrations/<rid>/evaluations", methods=["GET"])
def list_reg_evaluations(rid):
    require(["SchedulingCoordinator", "ProgramDesigner", "FinanceManager"])
    find_or_404(db.registrations, rid)
    a = request.args
    return list_response(db.evaluations.values(), [("registration_id", rid)], a)


@bp.route("/evaluations", methods=["GET"])
def list_evaluations():
    require(["SchedulingCoordinator", "ProgramDesigner", "FinanceManager"])
    a = request.args
    return list_response(db.evaluations.values(), [
        ("cohort_id", a.get("cohort_id")),
        ("registration_id", a.get("registration_id")),
    ], a)
