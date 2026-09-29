"""Verification cycle preparation, criteria deficiencies, surveyor bookings, the
site visit and the three-way decision (PRD 3.9)."""
from flask import Blueprint

import calc
import cascade
import serializers as ser
from auth import identity, require_authority, require_roles, require_scope
from common import D, days, new_record, num, sorted_records
from envelope import respond_list, respond_object, touch
from errors import ApiError
from store import clock_now, db
from validate import (
    check_enum,
    filter_eq,
    get_body,
    opt_int,
    paginate,
    query_enum,
    req_dt,
    req_int,
    req_str,
)

bp = Blueprint("cycles", __name__)

CYCLE_TYPES = ("NATIONAL_VERIFICATION", "STATE_DESIGNATION")
DEFICIENCY_CLASSES = ("TYPE_I_CRITICAL", "TYPE_II_MAJOR", "TYPE_III_MINOR")
DECISIONS = ("VERIFIED", "CONTINGENCY", "DENIED")
READINESS_VARIANTS = ("REVIEWER_ASSESSMENT", "SELF_ASSESSMENT")
AUTHORITIES = ["VerificationReviewer", "StateDesignationOfficer"]
DEFICIENCY_RECORDING_STATES = ("PREP", "PREP_BLOCKED", "UNDER_REVIEW", "CONTINGENCY")
BOOKING_STATES = ("SUBMITTED", "SITE_VISIT_SCHEDULED")
CYCLE_READ_ROLES = [
    "SystemAdmin",
    "TraumaProgramManager",
    "TraumaMedicalDirector",
    "VerificationReviewer",
    "StateDesignationOfficer",
]
BOOKING_READ_ROLES = [
    "SystemAdmin",
    "TraumaProgramManager",
    "VerificationReviewer",
    "StateDesignationOfficer",
]


def load_cycle(cycle_id):
    cycle = db.cycles.get(cycle_id)
    if cycle is None:
        raise ApiError("ERR_CYCLE_NOT_FOUND")
    return cycle


def load_deficiency(deficiency_id):
    record = db.deficiencies.get(deficiency_id)
    if record is None:
        raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND")
    return record


# --- the cycle itself -----------------------------------------------------


@bp.route("/verification-cycles", methods=["POST"])
def create_cycle():
    user_id, role = identity()
    require_roles(role, ["TraumaProgramManager"])
    body = get_body()
    center_raw = body.get("center_id")
    require_scope(user_id, role, center_raw if isinstance(center_raw, str) else None)
    center_id = req_str(body, "center_id")
    center = db.centers.get(center_id)
    if center is None:
        raise ApiError("ERR_CENTER_NOT_FOUND")
    cycle_type = req_str(body, "cycle_type")
    site_visit_date = req_dt(body, "site_visit_date")
    check_enum(cycle_type, CYCLE_TYPES)
    record = new_record()
    record.update(
        {
            "center_id": center_id,
            "cycle_type": cycle_type,
            "site_visit_date": site_visit_date,
            "status": "PREP",
            "readiness_score": 100.00,
            "open_type_i_count": 0,
            "open_type_ii_count": 0,
            "open_type_iii_count": 0,
            "decided_at": None,
            "decision_effective_date": None,
            "decision": None,
        }
    )
    db.cycles[record["id"]] = record
    # readiness is computed immediately under the reviewer variant; a brand new
    # cycle stays in PREP because the gate transitions are cascade-driven
    cascade.store_readiness(record)
    return respond_object(lambda: ser.cycle(record), 201)


@bp.route("/verification-cycles/<cycle_id>", methods=["GET"])
def read_cycle(cycle_id):
    user_id, role = identity()
    require_roles(role, CYCLE_READ_ROLES)
    cycle = load_cycle(cycle_id)
    return respond_object(lambda: ser.cycle(cycle))


@bp.route("/verification-cycles", methods=["GET"])
def list_cycles():
    user_id, role = identity()
    require_roles(role, CYCLE_READ_ROLES)
    records = sorted_records(list(db.cycles.values()))
    for field in ("center_id", "cycle_type", "status"):
        records = filter_eq(records, field)
    page, meta = paginate(records)
    return respond_list(lambda: [ser.cycle(r) for r in page], meta)


@bp.route("/verification-cycles/<cycle_id>/readiness", methods=["GET"])
def read_readiness(cycle_id):
    user_id, role = identity()
    require_roles(role, CYCLE_READ_ROLES)
    cycle = load_cycle(cycle_id)
    variant = query_enum("variant", READINESS_VARIANTS, "REVIEWER_ASSESSMENT")
    breakdown = calc.readiness_breakdown(cycle, variant)

    def build():
        return {
            "variant": breakdown["variant"],
            "base_score": num(breakdown["base_score"]),
            "deficiency_penalty": num(breakdown["deficiency_penalty"]),
            "outreach_penalty": num(breakdown["outreach_penalty"]),
            "pi_penalty": num(breakdown["pi_penalty"]),
            "readiness_score": num(breakdown["readiness_score"]),
            "submit_eligible": breakdown["readiness_score"] >= calc.SUBMIT_MIN_READINESS,
        }

    return respond_object(build)


# --- criteria deficiencies ------------------------------------------------


@bp.route("/verification-cycles/<cycle_id>/deficiencies", methods=["POST"])
def record_deficiency(cycle_id):
    user_id, role = identity()
    require_roles(role, AUTHORITIES)
    cycle = load_cycle(cycle_id)
    require_authority(role, cycle)
    body = get_body()
    criterion_code = req_str(body, "criterion_code")
    deficiency_class = req_str(body, "deficiency_class")
    remediation_due_at = req_dt(body, "remediation_due_at")
    check_enum(deficiency_class, DEFICIENCY_CLASSES)
    if cycle["status"] not in DEFICIENCY_RECORDING_STATES:
        raise ApiError("ERR_INVALID_CYCLE_STATE")
    if remediation_due_at <= clock_now():
        raise ApiError("ERR_INVALID_INTERVAL_DATES")
    record = new_record()
    record.update(
        {
            "verification_cycle_id": cycle_id,
            "criterion_code": criterion_code,
            "deficiency_class": deficiency_class,
            "status": "OPEN",
            "remediation_due_at": remediation_due_at,
            "remediation_note": None,
            "closed_at": None,
            "escalation_reason": None,
        }
    )
    db.deficiencies[record["id"]] = record
    cascade.refresh_cycle(cycle)
    touch(cycle)
    center = db.centers.get(cycle["center_id"])
    cascade.cascade_center(center)
    if center is not None:
        touch(center)
    return respond_object(lambda: ser.deficiency(record), 201)


@bp.route("/verification-cycles/<cycle_id>/deficiencies", methods=["GET"])
def list_deficiencies(cycle_id):
    user_id, role = identity()
    require_roles(role, CYCLE_READ_ROLES)
    cycle = load_cycle(cycle_id)
    records = calc.deficiencies_of_cycle(cycle_id)
    for field in ("deficiency_class", "status"):
        records = filter_eq(records, field)
    page, meta = paginate(records)
    return respond_list(lambda: [ser.deficiency(r) for r in page], meta)


@bp.route("/criteria-deficiencies/<deficiency_id>/remediation", methods=["POST"])
def submit_remediation(deficiency_id):
    user_id, role = identity()
    require_roles(role, ["TraumaProgramManager"])
    record = load_deficiency(deficiency_id)
    cycle = db.cycles.get(record["verification_cycle_id"])
    require_scope(user_id, role, cycle["center_id"] if cycle else None)
    body = get_body()
    expected = req_int(body, "expected_cycle_version")
    note = req_str(body, "remediation_note")
    if cycle is not None and expected != cycle["version"]:
        raise ApiError("ERR_STALE_CYCLE_VERSION")
    if record["status"] not in ("OPEN", "REMEDIATION_SUBMITTED", "ESCALATED"):
        raise ApiError("ERR_INVALID_DEFICIENCY_STATE")
    was_escalated = record["status"] == "ESCALATED"
    record["status"] = "REMEDIATION_SUBMITTED"
    record["remediation_note"] = note
    if cycle is not None:
        cascade.refresh_cycle(cycle)
        touch(cycle)
        if was_escalated:
            # climbing back out of ESCALATED releases the center's escalation count
            cascade.cascade_center(db.centers.get(cycle["center_id"]))
    return respond_object(lambda: ser.deficiency(record))


@bp.route("/criteria-deficiencies/<deficiency_id>/close", methods=["POST"])
def close_deficiency(deficiency_id):
    user_id, role = identity()
    require_roles(role, AUTHORITIES)
    record = load_deficiency(deficiency_id)
    cycle = db.cycles.get(record["verification_cycle_id"])
    require_authority(role, cycle)
    if record["status"] not in ("REMEDIATION_SUBMITTED", "ESCALATED"):
        raise ApiError("ERR_INVALID_DEFICIENCY_STATE")
    record["status"] = "CLOSED"
    record["closed_at"] = clock_now()
    if cycle is not None:
        cascade.refresh_cycle(cycle)
        touch(cycle)
        cascade.cascade_center(db.centers.get(cycle["center_id"]))
    return respond_object(lambda: ser.deficiency(record))


@bp.route("/criteria-deficiencies/<deficiency_id>/escalate", methods=["POST"])
def escalate_deficiency(deficiency_id):
    user_id, role = identity()
    require_roles(role, AUTHORITIES)
    record = load_deficiency(deficiency_id)
    cycle = db.cycles.get(record["verification_cycle_id"])
    body = get_body()
    reason = req_str(body, "escalation_reason")
    if record["status"] not in ("OPEN", "REMEDIATION_SUBMITTED"):
        raise ApiError("ERR_INVALID_DEFICIENCY_STATE")
    now = clock_now()
    record["status"] = "ESCALATED"
    record["remediation_due_at"] = now + days(calc.ESCALATION_REMEDIATION_DAYS)
    record["escalation_reason"] = reason
    center = db.centers.get(cycle["center_id"]) if cycle else None
    if center is not None:
        cascade.create_pi_event(
            center,
            "DEFICIENCY_ESCALATION",
            "HIGH",
            source_deficiency_id=deficiency_id,
            due_days=calc.ESCALATION_REMEDIATION_DAYS,
        )
    if cycle is not None:
        cascade.refresh_cycle(cycle)
        touch(cycle)
    cascade.cascade_center(center, cycles=True)
    return respond_object(lambda: ser.deficiency(record))


# --- surveyor bookings ----------------------------------------------------


@bp.route("/verification-cycles/<cycle_id>/surveyor-bookings", methods=["POST"])
def book_surveyor(cycle_id):
    user_id, role = identity()
    require_roles(role, AUTHORITIES)
    cycle = load_cycle(cycle_id)
    require_authority(role, cycle)
    body = get_body()
    surveyor_user_id = req_str(body, "surveyor_user_id")
    window_start = req_dt(body, "window_start")
    window_end = req_dt(body, "window_end")
    buffer_hours = opt_int(body, "travel_buffer_hours", lo=0, default=calc.TRAVEL_BUFFER_HOURS)
    if cycle["status"] not in BOOKING_STATES:
        raise ApiError("ERR_INVALID_CYCLE_STATE")
    if window_end <= window_start:
        raise ApiError("ERR_INVALID_INTERVAL_DATES")
    if calc.surveyor_conflict(surveyor_user_id, window_start, window_end, buffer_hours):
        raise ApiError("ERR_SURVEYOR_WINDOW_CONFLICT")
    record = new_record()
    record.update(
        {
            "verification_cycle_id": cycle_id,
            "surveyor_user_id": surveyor_user_id,
            "window_start": window_start,
            "window_end": window_end,
            "travel_buffer_hours": buffer_hours,
            # PRD 3.9: scheduling the site visit requires a booking made while
            # the cycle was SUBMITTED
            "_booked_in_status": cycle["status"],
        }
    )
    db.bookings[record["id"]] = record
    return respond_object(lambda: ser.booking(record), 201)


@bp.route("/verification-cycles/<cycle_id>/surveyor-bookings", methods=["GET"])
def list_bookings(cycle_id):
    user_id, role = identity()
    require_roles(role, BOOKING_READ_ROLES)
    cycle = load_cycle(cycle_id)
    records = calc.bookings_of_cycle(cycle_id)
    records = filter_eq(records, "surveyor_user_id")
    page, meta = paginate(records)
    return respond_list(lambda: [ser.booking(r) for r in page], meta)


# --- the lifecycle towards the decision -----------------------------------


@bp.route("/verification-cycles/<cycle_id>/submit", methods=["POST"])
def submit_cycle(cycle_id):
    user_id, role = identity()
    require_roles(role, ["TraumaProgramManager"])
    cycle = load_cycle(cycle_id)
    require_scope(user_id, role, cycle["center_id"])
    if cycle["status"] != "PREP":
        raise ApiError("ERR_INVALID_CYCLE_STATE")
    center = db.centers.get(cycle["center_id"])
    if center is not None and cascade.posture_of(center) == "SUSPENDED":
        raise ApiError("ERR_POSTURE_SUSPENDED")
    score = calc.readiness_score(cycle, "REVIEWER_ASSESSMENT")
    if score < calc.SUBMIT_MIN_READINESS:
        raise ApiError("ERR_READINESS_BELOW_THRESHOLD")
    # the value the reviewers will see is frozen at submission time
    cascade.refresh_cycle_counts(cycle)
    cycle["readiness_score"] = num(score)
    cycle["status"] = "SUBMITTED"
    touch(cycle)
    return respond_object(lambda: ser.cycle(cycle))


@bp.route("/verification-cycles/<cycle_id>/schedule-site-visit", methods=["POST"])
def schedule_site_visit(cycle_id):
    user_id, role = identity()
    require_roles(role, AUTHORITIES)
    cycle = load_cycle(cycle_id)
    body = get_body()
    site_visit_date = req_dt(body, "site_visit_date")
    if cycle["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_CYCLE_STATE")
    bookings = calc.bookings_of_cycle(cycle_id)
    if not [b for b in bookings if b.get("_booked_in_status") == "SUBMITTED"]:
        raise ApiError("ERR_INVALID_CYCLE_STATE")
    cycle["site_visit_date"] = site_visit_date
    cycle["status"] = "SITE_VISIT_SCHEDULED"
    touch(cycle)
    return respond_object(lambda: ser.cycle(cycle))


@bp.route("/verification-cycles/<cycle_id>/begin-review", methods=["POST"])
def begin_review(cycle_id):
    user_id, role = identity()
    require_roles(role, AUTHORITIES)
    cycle = load_cycle(cycle_id)
    require_authority(role, cycle)
    if cycle["status"] != "SITE_VISIT_SCHEDULED":
        raise ApiError("ERR_INVALID_CYCLE_STATE")
    if not calc.bookings_of_cycle(cycle_id):
        raise ApiError("ERR_INVALID_CYCLE_STATE")
    cycle["status"] = "UNDER_REVIEW"
    touch(cycle)
    return respond_object(lambda: ser.cycle(cycle))


@bp.route("/verification-cycles/<cycle_id>/decide", methods=["POST"])
def decide_cycle(cycle_id):
    user_id, role = identity()
    require_roles(role, AUTHORITIES)
    cycle = load_cycle(cycle_id)
    require_authority(role, cycle)
    body = get_body()
    decision = req_str(body, "decision")
    effective_date = req_dt(body, "decision_effective_date")
    check_enum(decision, DECISIONS)
    if cycle["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_CYCLE_STATE")
    if decision == "VERIFIED" and cycle["open_type_i_count"] != 0:
        raise ApiError("ERR_CRITICAL_DEFICIENCY_BLOCKS_VERIFICATION")
    now = clock_now()
    center = db.centers.get(cycle["center_id"])
    national = cycle["cycle_type"] == "NATIONAL_VERIFICATION"
    cycle["status"] = decision
    cycle["decision"] = decision
    cycle["decided_at"] = now
    cycle["decision_effective_date"] = effective_date
    escalated = 0
    if decision == "VERIFIED":
        if center is not None:
            if national:
                center["national_verification_status"] = "VERIFIED"
            else:
                center["state_designation_status"] = "DESIGNATED"
    elif decision == "DENIED":
        if center is not None:
            if national:
                center["national_verification_status"] = "SUSPENDED"
            else:
                # a lost state designation is a reporting event only
                center["state_designation_status"] = "WITHDRAWN"
    else:
        if center is not None:
            if national:
                center["national_verification_status"] = "CONTINGENCY"
            else:
                center["state_designation_status"] = "PROVISIONAL"
        targets = [
            d
            for d in calc.deficiencies_of_cycle(cycle_id)
            if d["deficiency_class"] == "TYPE_I_CRITICAL"
            and d["status"] in ("OPEN", "REMEDIATION_SUBMITTED")
        ]
        targets.sort(key=lambda d: (d["criterion_code"], d["created_at"], d["_seq"]))
        for target in targets:
            target["status"] = "ESCALATED"
            target["remediation_due_at"] = now + days(calc.ESCALATION_REMEDIATION_DAYS)
            escalated += 1
            if center is not None:
                cascade.create_pi_event(
                    center,
                    "DEFICIENCY_ESCALATION",
                    "HIGH",
                    source_deficiency_id=target["id"],
                    due_days=calc.ESCALATION_REMEDIATION_DAYS,
                )
    touch(cycle)
    cascade.cascade_center(center)
    if decision == "CONTINGENCY":
        # the cycle's own readiness is refreshed as part of the same decision
        cascade.refresh_cycle(cycle, gate=False)
        if escalated:
            cascade.refresh_cycles(center, cascade.NON_DECIDED)
    if center is not None:
        touch(center)
    return respond_object(lambda: ser.cycle(cycle))
