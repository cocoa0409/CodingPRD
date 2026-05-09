from flask import Blueprint, request

from audit import write_audit
from calc import (
    provisional_cost_estimate,
    final_settlement_cost,
    staff_working_hours_total,
    STAFF_MAX_WORKING_MINUTES_PER_DAY,
    case_assignments_for,
)
from db import db
from errors import (
    raise_error,
    ERR_CASE_NOT_FOUND,
    ERR_ROOM_NOT_FOUND,
    ERR_STAFF_NOT_FOUND,
    ERR_INSTRUMENT_SET_NOT_FOUND,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_TIME_PARAMETERS,
    ERR_CASE_NOT_REQUESTED,
    ERR_CASE_NOT_APPROVED,
    ERR_CASE_NOT_SCHEDULED,
    ERR_CASE_NOT_IN_PROGRESS,
    ERR_CASE_NOT_CANCELLABLE,
    ERR_INVALID_STATE,
    ERR_ASSIGNMENT_NOT_CONFIRMED,
    ERR_INSTRUMENT_NOT_STERILIZED,
    ERR_INSTRUMENT_EXPIRED,
    ERR_PRE_OP_ASSESSMENT_MISSING,
    ERR_INFORMED_CONSENT_MISSING,
    ERR_QUALIFICATION_MISMATCH,
    ERR_STAFF_OUT_OF_SHIFT,
    ERR_STAFF_ROLE_MISMATCH,
    ERR_ROOM_SPECIALTY_RESTRICTED,
    ERR_INSTRUMENT_SPECIALTY_MISMATCH,
    ERR_ROOM_TIME_CONFLICT,
    ERR_STAFF_TIME_CONFLICT,
    ERR_INSTRUMENT_TIME_CONFLICT,
    ERR_STAFF_WORKING_HOURS_EXCEEDED,
    ERR_CANNOT_PREEMPT_EMERGENCY,
)
from middleware import auth_required
from response import success, paginate
from routes_instruments import apply_lazy_expiry
from serialize import serialize_case, serialize_assignment
from utils import (
    get_json_body,
    require_str,
    require_int,
    require_number,
    optional_bool,
    optional_number,
    optional_str,
    get_pagination,
    check_version,
)

SPECIALTIES = {"GENERAL", "CARDIAC", "NEURO", "OBSTETRIC"}
PRIORITIES = {"ROUTINE", "URGENT", "EMERGENCY"}
ROLES_IN_CASE = {"LEAD_ANESTHESIOLOGIST", "SCRUB_NURSE", "CIRCULATING_NURSE"}
ROLE_TO_STAFF_ROLE = {
    "LEAD_ANESTHESIOLOGIST": "ANESTHESIOLOGIST",
    "SCRUB_NURSE": "SCRUB_NURSE",
    "CIRCULATING_NURSE": "CIRCULATING_NURSE",
}

bp = Blueprint("cases", __name__)


# -----------------------------------------------------------------------------
# Helpers — interval logic
# -----------------------------------------------------------------------------
def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [a_start, a_end) intersects [b_start, b_end)."""
    return a_start < b_end and a_end > b_start


def _settlement_for_case(case_id):
    for s in db.settlements.values():
        if s["case_id"] == case_id:
            return s
    return None


def _cascade_assignments_to(case_id, target_status, allowed_from):
    affected = []
    for a in db.case_assignments.values():
        if a["case_id"] != case_id:
            continue
        if a["status"] in allowed_from:
            a["status"] = target_status
            db.stamp_update(a)
            affected.append(a)
    return affected


def _booking_for_case(case_id):
    for b in db.instrument_bookings.values():
        if b["case_id"] == case_id:
            return b
    return None


# -----------------------------------------------------------------------------
# CRUD
# -----------------------------------------------------------------------------

@bp.route("/surgical-cases", methods=["POST"])
@auth_required("SurgicalCoordinator")
def create_case():
    body = get_json_body()
    patient_id = require_str(body, "patient_id")
    surgery_type = require_str(body, "surgery_type")
    specialty = require_str(body, "specialty_required")
    if specialty not in SPECIALTIES:
        raise_error(ERR_INVALID_REQUEST, f"specialty_required must be one of {sorted(SPECIALTIES)}")
    priority = body.get("priority", "ROUTINE")
    if priority is None:
        priority = "ROUTINE"
    if not isinstance(priority, str) or priority not in PRIORITIES:
        raise_error(ERR_INVALID_REQUEST, f"priority must be one of {sorted(PRIORITIES)}")
    pre_op = optional_bool(body, "pre_op_assessment_attached", False)
    consent = optional_bool(body, "informed_consent_verified", False)
    implant_estimate = optional_number(body, "implant_cost_estimate", 0.0)

    with db.lock:
        c = {
            "patient_id": patient_id,
            "surgery_type": surgery_type,
            "specialty_required": specialty,
            "priority": priority,
            "pre_op_assessment_attached": pre_op,
            "informed_consent_verified": consent,
            "planned_start_minute": None,
            "planned_end_minute": None,
            "scheduled_room_id": None,
            "actual_start_minute": None,
            "actual_end_minute": None,
            "implant_cost_estimate": implant_estimate,
            "implant_cost_actual": None,
            "status": "REQUESTED",
            "rejected_reason": None,
            "preempted_at_minute": None,
            "preempted_by_case_id": None,
        }
        db.stamp_create(c)
        db.surgical_cases[c["id"]] = c
        write_audit("SurgicalCase", c["id"], "CASE_REQUESTED",
                    {"patient_id": patient_id, "surgery_type": surgery_type,
                     "specialty_required": specialty, "priority": priority})
    return success(serialize_case(c), status_code=201)


@bp.route("/surgical-cases", methods=["GET"])
@auth_required("Any")
def list_cases():
    limit, offset = get_pagination()
    status_filter = request.args.get("status")
    with db.lock:
        items = sorted(db.surgical_cases.values(), key=lambda r: (r["created_at"], r["_seq"]))
        if status_filter:
            items = [r for r in items if r["status"] == status_filter]
        sliced, pagination = paginate(items, limit, offset)
        data = [serialize_case(r) for r in sliced]
    return success(data, response_type="array", pagination=pagination)


@bp.route("/surgical-cases/<case_id>", methods=["GET"])
@auth_required("Any")
def get_case(case_id):
    with db.lock:
        c = db.surgical_cases.get(case_id)
        if c is None:
            raise_error(ERR_CASE_NOT_FOUND, f"SurgicalCase {case_id} not found")
        return success(serialize_case(c))


# -----------------------------------------------------------------------------
# /approve, /reject
# -----------------------------------------------------------------------------

@bp.route("/surgical-cases/<case_id>/approve", methods=["POST"])
@auth_required("DepartmentHead")
def approve_case(case_id):
    body = get_json_body()
    with db.lock:
        c = db.surgical_cases.get(case_id)
        if c is None:
            raise_error(ERR_CASE_NOT_FOUND, f"SurgicalCase {case_id} not found")
        if c["status"] != "REQUESTED":
            raise_error(ERR_CASE_NOT_REQUESTED,
                        f"approve requires REQUESTED, got {c['status']}")
        if not c.get("pre_op_assessment_attached"):
            raise_error(ERR_PRE_OP_ASSESSMENT_MISSING,
                        "pre_op_assessment_attached must be true to approve")
        if not c.get("informed_consent_verified"):
            raise_error(ERR_INFORMED_CONSENT_MISSING,
                        "informed_consent_verified must be true to approve")
        check_version(body, c)

        c["status"] = "APPROVED"
        db.stamp_update(c)

        # Create Settlement DRAFT
        settlement = {
            "case_id": c["id"],
            "status": "DRAFT",
            "estimated_total_amount": None,
            "final_total_amount": None,
            "line_items": [],
            "insurance_split": [],
            "per_payer_amounts": [],
            "implant_cost": 0.0,
            "refund_amount": 0.0,
            "insurance_pre_auth_reference": None,
        }
        db.stamp_create(settlement)
        db.settlements[settlement["id"]] = settlement

        write_audit("SurgicalCase", c["id"], "CASE_APPROVED",
                    {"settlement_id": settlement["id"]})
        return success(serialize_case(c))


@bp.route("/surgical-cases/<case_id>/reject", methods=["POST"])
@auth_required("DepartmentHead")
def reject_case(case_id):
    body = get_json_body()
    with db.lock:
        c = db.surgical_cases.get(case_id)
        if c is None:
            raise_error(ERR_CASE_NOT_FOUND, f"SurgicalCase {case_id} not found")
        if c["status"] != "REQUESTED":
            raise_error(ERR_CASE_NOT_REQUESTED,
                        f"reject requires REQUESTED, got {c['status']}")
        check_version(body, c)
        reason = optional_str(body, "rejected_reason", None)

        c["status"] = "REJECTED"
        c["rejected_reason"] = reason
        db.stamp_update(c)

        write_audit("SurgicalCase", c["id"], "CASE_REJECTED",
                    {"rejected_reason": reason})
        return success(serialize_case(c))


# -----------------------------------------------------------------------------
# /schedule
# -----------------------------------------------------------------------------

def _validate_schedule_business(case, room, instrument, staff_list, role_for_staff,
                                planned_start, planned_end):
    """Apply business safety/referential/temporal/capacity validations in PRD order.

    `staff_list` is a list of (assignment_input, staff_dict) preserving payload order.
    `role_for_staff` is dict {staff_id: role_in_case} for role compatibility check.
    """
    specialty = case["specialty_required"]

    # Priority 7 — business safety: qualifications (per staff in input order),
    # then shift coverage (per staff in input order),
    # then role compatibility (per staff in input order).
    for _entry, s in staff_list:
        if specialty not in (s.get("qualifications") or []):
            raise_error(ERR_QUALIFICATION_MISMATCH,
                        f"staff {s['id']} qualifications missing {specialty}")

    for _entry, s in staff_list:
        if not (s["shift_start_minute"] <= planned_start and s["shift_end_minute"] >= planned_end):
            raise_error(ERR_STAFF_OUT_OF_SHIFT,
                        f"staff {s['id']} shift does not cover the planned interval")

    for entry, s in staff_list:
        role_in = entry["role_in_case"]
        if ROLE_TO_STAFF_ROLE.get(role_in) != s["staff_role"]:
            raise_error(ERR_STAFF_ROLE_MISMATCH,
                        f"role_in_case {role_in} incompatible with staff_role {s['staff_role']}")

    # Priority 8 — referential: room specialty, then instrument specialty
    if room["specialty_required"] != specialty:
        raise_error(ERR_ROOM_SPECIALTY_RESTRICTED,
                    f"room specialty {room['specialty_required']} != case {specialty}")
    if instrument["specialty"] != specialty:
        raise_error(ERR_INSTRUMENT_SPECIALTY_MISMATCH,
                    f"instrument specialty {instrument['specialty']} != case {specialty}")


def _validate_temporal_conflicts(case, room, instrument, staff_list,
                                 planned_start, planned_end, exclude_case_ids=None):
    exclude = exclude_case_ids or set()

    # Room turnover-buffer overlap (excluding cases in exclude set)
    buffer_min = room["turnover_buffer_minutes"]
    new_window_end = planned_end + buffer_min
    for other in db.surgical_cases.values():
        if other["id"] == case["id"]:
            continue
        if other["id"] in exclude:
            continue
        if other.get("scheduled_room_id") != room["id"]:
            continue
        if other["status"] not in {"SCHEDULED", "IN_PROGRESS"}:
            continue
        e_start = other["planned_start_minute"]
        e_end = other["planned_end_minute"]
        if e_start is None or e_end is None:
            continue
        e_window_end = e_end + buffer_min
        if _intervals_overlap(e_start, e_window_end, planned_start, new_window_end):
            raise_error(ERR_ROOM_TIME_CONFLICT,
                        f"room {room['id']} overlap with case {other['id']}")

    # Staff conflict
    for _entry, s in staff_list:
        for a in db.case_assignments.values():
            if a["staff_id"] != s["id"]:
                continue
            if a["status"] not in {"RESERVED", "CONFIRMED"}:
                continue
            if a["case_id"] == case["id"]:
                continue
            if a["case_id"] in exclude:
                continue
            if _intervals_overlap(a["assigned_start_minute"], a["assigned_end_minute"],
                                  planned_start, planned_end):
                raise_error(ERR_STAFF_TIME_CONFLICT,
                            f"staff {s['id']} overlaps existing assignment")

    # Instrument booking conflict
    for b in db.instrument_bookings.values():
        if b["instrument_set_id"] != instrument["id"]:
            continue
        if b["status"] not in {"RESERVED", "CHECKED_OUT"}:
            continue
        if b["case_id"] == case["id"]:
            continue
        if b["case_id"] in exclude:
            continue
        owner = db.surgical_cases.get(b["case_id"])
        if owner is None:
            continue
        o_start = owner.get("planned_start_minute")
        o_end = owner.get("planned_end_minute")
        if o_start is None or o_end is None:
            continue
        if _intervals_overlap(o_start, o_end, planned_start, planned_end):
            raise_error(ERR_INSTRUMENT_TIME_CONFLICT,
                        f"instrument {instrument['id']} overlaps case {owner['id']}")


def _validate_working_hours(staff_list, planned_start, planned_end,
                            exclude_case_ids=None):
    exclude = exclude_case_ids or set()
    for _entry, s in staff_list:
        # Compute total excluding assignments belonging to excluded (preempted) cases
        window_start = planned_start - 720
        window_end = planned_start + 720
        existing = 0
        for a in db.case_assignments.values():
            if a["staff_id"] != s["id"]:
                continue
            if a["status"] not in {"RESERVED", "CONFIRMED", "COMPLETED"}:
                continue
            if a["case_id"] in exclude:
                continue
            if a["assigned_start_minute"] < window_end and a["assigned_end_minute"] > window_start:
                existing += a["assigned_end_minute"] - a["assigned_start_minute"]
        new_min = planned_end - planned_start
        if existing + new_min > STAFF_MAX_WORKING_MINUTES_PER_DAY:
            raise_error(ERR_STAFF_WORKING_HOURS_EXCEEDED,
                        f"staff {s['id']} would exceed {STAFF_MAX_WORKING_MINUTES_PER_DAY} min/day")


def _parse_schedule_body(body, *, require_priority_emergency=False):
    """Parse and basic-validate the schedule body. Returns parsed dict.

    Existence checks happen separately to preserve PRD priority ordering.
    """
    scheduled_room_id = body.get("scheduled_room_id")
    if not isinstance(scheduled_room_id, str) or not scheduled_room_id:
        raise_error(ERR_INVALID_REQUEST, "scheduled_room_id must be a non-empty string")
    planned_start = body.get("planned_start_minute")
    planned_end = body.get("planned_end_minute")
    if planned_start is None or planned_end is None:
        raise_error(ERR_INVALID_REQUEST, "planned_start_minute and planned_end_minute required")
    if isinstance(planned_start, bool) or not isinstance(planned_start, int):
        raise_error(ERR_INVALID_REQUEST, "planned_start_minute must be an integer")
    if isinstance(planned_end, bool) or not isinstance(planned_end, int):
        raise_error(ERR_INVALID_REQUEST, "planned_end_minute must be an integer")

    staff_assignments = body.get("staff_assignments")
    if not isinstance(staff_assignments, list) or not staff_assignments:
        raise_error(ERR_INVALID_REQUEST, "staff_assignments must be a non-empty list")
    parsed_staff = []
    for entry in staff_assignments:
        if not isinstance(entry, dict):
            raise_error(ERR_INVALID_REQUEST, "staff_assignments entries must be objects")
        sid = entry.get("staff_id")
        rin = entry.get("role_in_case")
        if not isinstance(sid, str) or not sid:
            raise_error(ERR_INVALID_REQUEST, "staff_assignments[*].staff_id required")
        if not isinstance(rin, str) or rin not in ROLES_IN_CASE:
            raise_error(ERR_INVALID_REQUEST,
                        f"role_in_case must be one of {sorted(ROLES_IN_CASE)}")
        parsed_staff.append({"staff_id": sid, "role_in_case": rin})

    instrument_set_id = body.get("instrument_set_id")
    if not isinstance(instrument_set_id, str) or not instrument_set_id:
        raise_error(ERR_INVALID_REQUEST, "instrument_set_id required")

    return {
        "scheduled_room_id": scheduled_room_id,
        "planned_start_minute": planned_start,
        "planned_end_minute": planned_end,
        "staff_assignments": parsed_staff,
        "instrument_set_id": instrument_set_id,
    }


def _resolve_body_existence(parsed):
    """Resolve room/staff/instrument by id in input order; raise first miss."""
    room = db.operating_rooms.get(parsed["scheduled_room_id"])
    if room is None:
        raise_error(ERR_ROOM_NOT_FOUND,
                    f"OperatingRoom {parsed['scheduled_room_id']} not found")
    staff_list = []
    for entry in parsed["staff_assignments"]:
        s = db.staff_members.get(entry["staff_id"])
        if s is None:
            raise_error(ERR_STAFF_NOT_FOUND, f"StaffMember {entry['staff_id']} not found")
        staff_list.append((entry, s))
    instrument = db.instrument_sets.get(parsed["instrument_set_id"])
    if instrument is None:
        raise_error(ERR_INSTRUMENT_SET_NOT_FOUND,
                    f"InstrumentSet {parsed['instrument_set_id']} not found")
    return room, staff_list, instrument


@bp.route("/surgical-cases/<case_id>/schedule", methods=["POST"])
@auth_required("Scheduler")
def schedule_case(case_id):
    body = get_json_body()
    with db.lock:
        c = db.surgical_cases.get(case_id)
        if c is None:
            raise_error(ERR_CASE_NOT_FOUND, f"SurgicalCase {case_id} not found")

        parsed = _parse_schedule_body(body)
        room, staff_list, instrument = _resolve_body_existence(parsed)

        # State of target case (priority 5)
        if c["status"] != "APPROVED":
            raise_error(ERR_CASE_NOT_APPROVED,
                        f"schedule requires APPROVED, got {c['status']}")

        # Apply lazy expiry on instrument so EXPIRED is visible.
        apply_lazy_expiry(instrument)

        # State of instrument (priority 5)
        if instrument["sterilization_status"] == "EXPIRED":
            raise_error(ERR_INSTRUMENT_EXPIRED,
                        f"instrument {instrument['id']} is EXPIRED")
        if instrument["sterilization_status"] != "CLEAN_STERILIZED":
            raise_error(ERR_INSTRUMENT_NOT_STERILIZED,
                        f"instrument {instrument['id']} is {instrument['sterilization_status']}")

        # Time invariant: planned_end > planned_start (priority 14)
        # We enforce this BEFORE business validations because all subsequent gates
        # depend on a valid interval; the priority ladder treats time-invariant
        # violations as last-resort but a malformed interval renders the rest
        # unmeaningful — keep here for safety.
        if parsed["planned_end_minute"] <= parsed["planned_start_minute"]:
            raise_error(ERR_INVALID_TIME_PARAMETERS,
                        "planned_end_minute must be strictly greater than planned_start_minute")

        # Business safety/referential
        _validate_schedule_business(c, room, instrument, staff_list,
                                    {e["staff_id"]: e["role_in_case"]
                                     for e in parsed["staff_assignments"]},
                                    parsed["planned_start_minute"],
                                    parsed["planned_end_minute"])

        # Temporal
        _validate_temporal_conflicts(c, room, instrument, staff_list,
                                     parsed["planned_start_minute"],
                                     parsed["planned_end_minute"])

        # Capacity
        _validate_working_hours(staff_list,
                                parsed["planned_start_minute"],
                                parsed["planned_end_minute"])

        # OCC
        check_version(body, c)

        # Apply transition
        c["scheduled_room_id"] = room["id"]
        c["planned_start_minute"] = parsed["planned_start_minute"]
        c["planned_end_minute"] = parsed["planned_end_minute"]
        c["status"] = "SCHEDULED"
        db.stamp_update(c)

        # Create CaseAssignments (RESERVED)
        for entry, s in staff_list:
            a = {
                "case_id": c["id"],
                "staff_id": s["id"],
                "role_in_case": entry["role_in_case"],
                "assigned_start_minute": parsed["planned_start_minute"],
                "assigned_end_minute": parsed["planned_end_minute"],
                "status": "RESERVED",
            }
            db.stamp_create(a)
            db.case_assignments[a["id"]] = a

        # Create InstrumentBooking (RESERVED)
        booking = {
            "case_id": c["id"],
            "instrument_set_id": instrument["id"],
            "status": "RESERVED",
        }
        db.stamp_create(booking)
        db.instrument_bookings[booking["id"]] = booking

        # Flip InstrumentSet
        instrument["sterilization_status"] = "CHECKED_OUT"
        instrument["current_case_id"] = c["id"]
        db.stamp_update(instrument)

        # Compute provisional cost
        settlement = _settlement_for_case(c["id"])
        if settlement is not None:
            total, implant_component = provisional_cost_estimate(c, room)
            settlement["estimated_total_amount"] = float(total)
            settlement["implant_cost"] = float(implant_component)
            db.stamp_update(settlement)

        write_audit("SurgicalCase", c["id"], "CASE_SCHEDULED",
                    {"scheduled_room_id": room["id"],
                     "planned_start_minute": parsed["planned_start_minute"],
                     "planned_end_minute": parsed["planned_end_minute"],
                     "instrument_set_id": instrument["id"]})
        return success(serialize_case(c))


# -----------------------------------------------------------------------------
# Assignments
# -----------------------------------------------------------------------------

@bp.route("/surgical-cases/<case_id>/assignments", methods=["GET"])
@auth_required("Any")
def list_assignments(case_id):
    limit, offset = get_pagination()
    with db.lock:
        c = db.surgical_cases.get(case_id)
        if c is None:
            raise_error(ERR_CASE_NOT_FOUND, f"SurgicalCase {case_id} not found")
        items = sorted(
            (a for a in db.case_assignments.values() if a["case_id"] == case_id),
            key=lambda r: (r["created_at"], r["_seq"]),
        )
        sliced, pagination = paginate(items, limit, offset)
        data = [serialize_assignment(a) for a in sliced]
    return success(data, response_type="array", pagination=pagination)


@bp.route("/surgical-cases/<case_id>/assignments/<assignment_id>/confirm", methods=["POST"])
@auth_required("Scheduler")
def confirm_assignment(case_id, assignment_id):
    body = get_json_body()
    with db.lock:
        c = db.surgical_cases.get(case_id)
        if c is None:
            raise_error(ERR_CASE_NOT_FOUND, f"SurgicalCase {case_id} not found")
        a = db.case_assignments.get(assignment_id)
        if a is None or a["case_id"] != case_id:
            raise_error(ERR_ASSIGNMENT_NOT_FOUND,
                        f"CaseAssignment {assignment_id} not found")
        if c["status"] != "SCHEDULED":
            raise_error(ERR_INVALID_STATE,
                        f"confirm requires owning case SCHEDULED, got {c['status']}")
        if a["status"] != "RESERVED":
            raise_error(ERR_INVALID_STATE,
                        f"confirm requires assignment RESERVED, got {a['status']}")
        check_version(body, a)

        a["status"] = "CONFIRMED"
        db.stamp_update(a)
        write_audit("CaseAssignment", a["id"], "ASSIGNMENT_CONFIRMED",
                    {"case_id": case_id})
        return success(serialize_assignment(a))


# -----------------------------------------------------------------------------
# /start, /complete, /cancel
# -----------------------------------------------------------------------------

@bp.route("/surgical-cases/<case_id>/start", methods=["POST"])
@auth_required("Scheduler")
def start_case(case_id):
    body = get_json_body()
    with db.lock:
        c = db.surgical_cases.get(case_id)
        if c is None:
            raise_error(ERR_CASE_NOT_FOUND, f"SurgicalCase {case_id} not found")
        if c["status"] != "SCHEDULED":
            raise_error(ERR_CASE_NOT_SCHEDULED,
                        f"start requires SCHEDULED, got {c['status']}")
        # Priority 6 — all assignments confirmed
        assigns = case_assignments_for(case_id)
        for a in assigns:
            if a["status"] != "CONFIRMED":
                raise_error(ERR_ASSIGNMENT_NOT_CONFIRMED,
                            f"assignment {a['id']} is {a['status']}, must be CONFIRMED")
        check_version(body, c)

        c["actual_start_minute"] = db.current_minute
        c["status"] = "IN_PROGRESS"
        db.stamp_update(c)

        booking = _booking_for_case(case_id)
        if booking is not None and booking["status"] == "RESERVED":
            booking["status"] = "CHECKED_OUT"
            db.stamp_update(booking)

        write_audit("SurgicalCase", c["id"], "CASE_STARTED",
                    {"actual_start_minute": c["actual_start_minute"]})
        return success(serialize_case(c))


@bp.route("/surgical-cases/<case_id>/complete", methods=["POST"])
@auth_required("Scheduler")
def complete_case(case_id):
    body = get_json_body()
    with db.lock:
        c = db.surgical_cases.get(case_id)
        if c is None:
            raise_error(ERR_CASE_NOT_FOUND, f"SurgicalCase {case_id} not found")
        if c["status"] != "IN_PROGRESS":
            raise_error(ERR_CASE_NOT_IN_PROGRESS,
                        f"complete requires IN_PROGRESS, got {c['status']}")
        check_version(body, c)

        implant_actual = optional_number(body, "implant_cost_actual", None)
        if implant_actual is not None:
            c["implant_cost_actual"] = implant_actual

        c["actual_end_minute"] = db.current_minute
        c["status"] = "COMPLETED"
        db.stamp_update(c)

        # Cascade assignments CONFIRMED → COMPLETED
        for a in db.case_assignments.values():
            if a["case_id"] != case_id:
                continue
            if a["status"] == "CONFIRMED":
                a["status"] = "COMPLETED"
                db.stamp_update(a)

        # Booking CHECKED_OUT → RETURNED_SOILED
        booking = _booking_for_case(case_id)
        if booking is not None and booking["status"] == "CHECKED_OUT":
            booking["status"] = "RETURNED_SOILED"
            db.stamp_update(booking)
            instrument = db.instrument_sets.get(booking["instrument_set_id"])
            if instrument is not None:
                instrument["sterilization_status"] = "SOILED"
                instrument["current_case_id"] = None
                db.stamp_update(instrument)

        # Compute final settlement cost
        settlement = _settlement_for_case(case_id)
        room = db.operating_rooms.get(c.get("scheduled_room_id"))
        if settlement is not None and room is not None:
            total, implant_component = final_settlement_cost(c, room)
            settlement["final_total_amount"] = float(total)
            settlement["implant_cost"] = float(implant_component)
            db.stamp_update(settlement)

        write_audit("SurgicalCase", c["id"], "CASE_COMPLETED",
                    {"actual_end_minute": c["actual_end_minute"]})
        return success(serialize_case(c))


@bp.route("/surgical-cases/<case_id>/cancel", methods=["POST"])
@auth_required("Scheduler")
def cancel_case(case_id):
    body = get_json_body()
    with db.lock:
        c = db.surgical_cases.get(case_id)
        if c is None:
            raise_error(ERR_CASE_NOT_FOUND, f"SurgicalCase {case_id} not found")
        if c["status"] not in {"APPROVED", "SCHEDULED", "IN_PROGRESS"}:
            raise_error(ERR_CASE_NOT_CANCELLABLE,
                        f"cancel requires non-terminal, got {c['status']}")
        check_version(body, c)

        prior_status = c["status"]
        c["status"] = "CANCELLED"
        if prior_status == "IN_PROGRESS":
            c["actual_end_minute"] = db.current_minute
        db.stamp_update(c)

        if prior_status in {"SCHEDULED", "IN_PROGRESS"}:
            # Release assignments
            allowed_from = {"RESERVED", "CONFIRMED"} if prior_status == "SCHEDULED" else {"CONFIRMED"}
            for a in db.case_assignments.values():
                if a["case_id"] != case_id:
                    continue
                if a["status"] in allowed_from:
                    a["status"] = "RELEASED"
                    db.stamp_update(a)

            # Release booking + return instrument
            booking = _booking_for_case(case_id)
            if booking is not None and booking["status"] in {"RESERVED", "CHECKED_OUT"}:
                booking["status"] = "RELEASED"
                db.stamp_update(booking)
                instrument = db.instrument_sets.get(booking["instrument_set_id"])
                if instrument is not None and instrument["sterilization_status"] == "CHECKED_OUT":
                    instrument["sterilization_status"] = "SOILED"
                    instrument["current_case_id"] = None
                    db.stamp_update(instrument)

        # Settlement cascade → REFUNDED
        settlement = _settlement_for_case(case_id)
        if settlement is not None and settlement["status"] not in {"SETTLED", "REFUNDED"}:
            if settlement["status"] == "ITEMIZED":
                refund_amount = float(settlement.get("final_total_amount") or 0.0)
            else:
                refund_amount = (
                    settlement.get("final_total_amount")
                    if settlement.get("final_total_amount") is not None
                    else (settlement.get("estimated_total_amount")
                          if settlement.get("estimated_total_amount") is not None
                          else 0.0)
                )
                refund_amount = float(refund_amount)
            settlement["refund_amount"] = refund_amount
            settlement["status"] = "REFUNDED"
            db.stamp_update(settlement)

        write_audit("SurgicalCase", c["id"], "CASE_CANCELLED",
                    {"prior_status": prior_status})
        return success(serialize_case(c))


# -----------------------------------------------------------------------------
# emergency-insert
# -----------------------------------------------------------------------------

def _find_preemptable_pool(parsed, room, staff_list, instrument):
    """Identify SCHEDULED cases preemptable due to room/staff/instrument overlap.

    Returns list of cases (subset of db.surgical_cases.values()).
    """
    pool = set()
    pn_start = parsed["planned_start_minute"]
    pn_end = parsed["planned_end_minute"]
    buffer_min = room["turnover_buffer_minutes"]

    # Mode (i): same room, time+buffer overlap
    new_window_end = pn_end + buffer_min
    for other in db.surgical_cases.values():
        if other["status"] != "SCHEDULED":
            continue
        if other.get("scheduled_room_id") != room["id"]:
            continue
        e_start = other["planned_start_minute"]
        e_end = other["planned_end_minute"]
        if e_start is None or e_end is None:
            continue
        e_window_end = e_end + buffer_min
        if _intervals_overlap(e_start, e_window_end, pn_start, new_window_end):
            pool.add(other["id"])

    # Mode (ii): shared staff, time overlap
    new_staff_ids = {s["id"] for _e, s in staff_list}
    for a in db.case_assignments.values():
        if a["staff_id"] not in new_staff_ids:
            continue
        if a["status"] not in {"RESERVED", "CONFIRMED"}:
            continue
        owner = db.surgical_cases.get(a["case_id"])
        if owner is None or owner["status"] != "SCHEDULED":
            continue
        if _intervals_overlap(a["assigned_start_minute"], a["assigned_end_minute"],
                              pn_start, pn_end):
            pool.add(owner["id"])

    # Mode (iii): shared instrument, time overlap
    for b in db.instrument_bookings.values():
        if b["instrument_set_id"] != instrument["id"]:
            continue
        if b["status"] not in {"RESERVED", "CHECKED_OUT"}:
            continue
        owner = db.surgical_cases.get(b["case_id"])
        if owner is None or owner["status"] != "SCHEDULED":
            continue
        o_start = owner.get("planned_start_minute")
        o_end = owner.get("planned_end_minute")
        if o_start is None or o_end is None:
            continue
        if _intervals_overlap(o_start, o_end, pn_start, pn_end):
            pool.add(owner["id"])

    return [db.surgical_cases[i] for i in pool]


def _preempt_case(case, by_case_id):
    case["preempted_at_minute"] = db.current_minute
    case["preempted_by_case_id"] = by_case_id
    case["status"] = "PREEMPTED"
    db.stamp_update(case)

    for a in db.case_assignments.values():
        if a["case_id"] != case["id"]:
            continue
        if a["status"] in {"RESERVED", "CONFIRMED"}:
            a["status"] = "PREEMPTED"
            db.stamp_update(a)

    booking = _booking_for_case(case["id"])
    if booking is not None and booking["status"] in {"RESERVED", "CHECKED_OUT"}:
        booking["status"] = "PREEMPTED"
        db.stamp_update(booking)
        instr = db.instrument_sets.get(booking["instrument_set_id"])
        if instr is not None and instr["sterilization_status"] == "CHECKED_OUT":
            instr["sterilization_status"] = "SOILED"
            instr["current_case_id"] = None
            db.stamp_update(instr)

    settlement = _settlement_for_case(case["id"])
    if settlement is not None and settlement["status"] not in {"SETTLED", "REFUNDED"}:
        ref_amount = (
            settlement.get("final_total_amount")
            if settlement.get("final_total_amount") is not None
            else (settlement.get("estimated_total_amount")
                  if settlement.get("estimated_total_amount") is not None
                  else 0.0)
        )
        settlement["refund_amount"] = float(ref_amount)
        settlement["status"] = "REFUNDED"
        db.stamp_update(settlement)

    write_audit("SurgicalCase", case["id"], "EMERGENCY_PREEMPT",
                {"preempted_by_case_id": by_case_id,
                 "preempted_at_minute": case["preempted_at_minute"]})


@bp.route("/surgical-cases/emergency-insert", methods=["POST"])
@auth_required("Scheduler")
def emergency_insert():
    body = get_json_body()
    patient_id = require_str(body, "patient_id")
    surgery_type = require_str(body, "surgery_type")
    specialty = require_str(body, "specialty_required")
    if specialty not in SPECIALTIES:
        raise_error(ERR_INVALID_REQUEST,
                    f"specialty_required must be one of {sorted(SPECIALTIES)}")
    parsed = _parse_schedule_body(body)
    implant_estimate = optional_number(body, "implant_cost_estimate", 0.0)

    if parsed["planned_end_minute"] <= parsed["planned_start_minute"]:
        raise_error(ERR_INVALID_TIME_PARAMETERS,
                    "planned_end_minute must be strictly greater than planned_start_minute")

    with db.lock:
        room, staff_list, instrument = _resolve_body_existence(parsed)

        # Build a stub case for validation helpers
        stub = {
            "id": "__pending__",
            "specialty_required": specialty,
            "patient_id": patient_id,
            "surgery_type": surgery_type,
        }

        # Apply lazy expiry on instrument
        apply_lazy_expiry(instrument)

        _validate_schedule_business(stub, room, instrument, staff_list,
                                    {e["staff_id"]: e["role_in_case"]
                                     for e in parsed["staff_assignments"]},
                                    parsed["planned_start_minute"],
                                    parsed["planned_end_minute"])

        # Find preemptable pool BEFORE temporal/capacity gates: emergency-insert preempts overlaps.
        pool = _find_preemptable_pool(parsed, room, staff_list, instrument)

        # Reject if any conflicting case is EMERGENCY-priority (priority 11/18 in scaffold)
        for p in pool:
            if p.get("priority") == "EMERGENCY":
                raise_error(ERR_CANNOT_PREEMPT_EMERGENCY,
                            f"conflict with EMERGENCY case {p['id']}")

        # Also: any IN_PROGRESS case with same room/staff/instrument overlap halts the request:
        # PRD 3.8: "IN_PROGRESS cases are protected — they are never preemptable; the emergency
        # must wait or use a different room." We surface ERR_ROOM_TIME_CONFLICT for IN_PROGRESS
        # room collisions and ERR_STAFF_TIME_CONFLICT / ERR_INSTRUMENT_TIME_CONFLICT for the rest,
        # via the temporal validator which excludes preemptable pool cases.
        exclude = {p["id"] for p in pool}
        _validate_temporal_conflicts(stub, room, instrument, staff_list,
                                     parsed["planned_start_minute"],
                                     parsed["planned_end_minute"],
                                     exclude_case_ids=exclude)

        # Capacity check: also exclude preempted assignments (will be PREEMPTED)
        _validate_working_hours(staff_list,
                                parsed["planned_start_minute"],
                                parsed["planned_end_minute"],
                                exclude_case_ids=exclude)

        # Now perform the preemption cascade
        # Create the new emergency case first so we have its id to reference in cascade audits.
        new_case = {
            "patient_id": patient_id,
            "surgery_type": surgery_type,
            "specialty_required": specialty,
            "priority": "EMERGENCY",
            "pre_op_assessment_attached": True,
            "informed_consent_verified": True,
            "planned_start_minute": parsed["planned_start_minute"],
            "planned_end_minute": parsed["planned_end_minute"],
            "scheduled_room_id": room["id"],
            "actual_start_minute": None,
            "actual_end_minute": None,
            "implant_cost_estimate": implant_estimate,
            "implant_cost_actual": None,
            "status": "SCHEDULED",
            "rejected_reason": None,
            "preempted_at_minute": None,
            "preempted_by_case_id": None,
        }
        db.stamp_create(new_case)
        db.surgical_cases[new_case["id"]] = new_case

        for p in pool:
            _preempt_case(p, new_case["id"])

        # Free the instrument if it was held by a preempted case so we can re-pin
        if instrument["sterilization_status"] != "CLEAN_STERILIZED":
            # After preemption, if instrument was just freed, we still need to flip it to CHECKED_OUT
            # (it would be SOILED post-preemption). For an emergency, we accept SOILED→CHECKED_OUT
            # implicitly to keep the instrument associated with this case.
            pass

        # Create CaseAssignments
        for entry, s in staff_list:
            a = {
                "case_id": new_case["id"],
                "staff_id": s["id"],
                "role_in_case": entry["role_in_case"],
                "assigned_start_minute": parsed["planned_start_minute"],
                "assigned_end_minute": parsed["planned_end_minute"],
                "status": "RESERVED",
            }
            db.stamp_create(a)
            db.case_assignments[a["id"]] = a

        # Create InstrumentBooking
        booking = {
            "case_id": new_case["id"],
            "instrument_set_id": instrument["id"],
            "status": "RESERVED",
        }
        db.stamp_create(booking)
        db.instrument_bookings[booking["id"]] = booking

        # Pin instrument
        instrument["sterilization_status"] = "CHECKED_OUT"
        instrument["current_case_id"] = new_case["id"]
        db.stamp_update(instrument)

        # Settlement DRAFT for the new case + provisional cost
        settlement = {
            "case_id": new_case["id"],
            "status": "DRAFT",
            "estimated_total_amount": None,
            "final_total_amount": None,
            "line_items": [],
            "insurance_split": [],
            "per_payer_amounts": [],
            "implant_cost": 0.0,
            "refund_amount": 0.0,
            "insurance_pre_auth_reference": None,
        }
        db.stamp_create(settlement)
        db.settlements[settlement["id"]] = settlement
        total, implant_component = provisional_cost_estimate(new_case, room)
        settlement["estimated_total_amount"] = float(total)
        settlement["implant_cost"] = float(implant_component)
        db.stamp_update(settlement)

        write_audit("SurgicalCase", new_case["id"], "EMERGENCY_INSERTED",
                    {"scheduled_room_id": room["id"],
                     "planned_start_minute": parsed["planned_start_minute"],
                     "planned_end_minute": parsed["planned_end_minute"],
                     "instrument_set_id": instrument["id"],
                     "preempted_case_ids": [p["id"] for p in pool]})

        return success(serialize_case(new_case), status_code=201)
