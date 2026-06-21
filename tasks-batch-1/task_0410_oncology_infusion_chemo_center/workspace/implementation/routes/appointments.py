"""InfusionAppointment endpoints, OCC booking, and lifecycle."""
from flask import Blueprint, request

import errors
from db import db
from errors import err
from middleware import get_auth, require_roles
from response import success, list_success
from store_helpers import (
    make_common, touch, public, sort_by_created,
    get_appointment, get_cycle, get_chair, get_nurse,
)
from validation import (
    get_body, require_str, require_int, require_datetime, parse_datetime,
    get_pagination, paginate,
)

bp = Blueprint("appointments", __name__)

ALL_ROLES = {"Pharmacist", "Nurse", "PriorAuthCoordinator"}
OCCUPYING_STATES = {"SCHEDULED", "CHECKED_IN"}


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open overlap: a_start < b_end AND b_start < a_end. Adjacency does not overlap."""
    return a_start < b_end and b_start < a_end


@bp.route("/infusion-appointments", methods=["POST"])
def create_appointment():
    _, role = get_auth()
    require_roles(role, {"Pharmacist", "Nurse"})
    body = get_body()

    # Existence: FK ids resolved left-to-right (cycle, chair, nurse).
    cycle_id = require_str(body, "treatment_cycle_id")
    cycle = get_cycle(cycle_id)
    chair_id = require_str(body, "chair_id")
    chair = get_chair(chair_id)
    nurse_id = require_str(body, "nurse_id")
    nurse = get_nurse(nurse_id)

    # Body well-formedness (priority 4): datetimes, end>start, acuity range, version present.
    start_at = require_datetime(body, "start_at")
    end_at = require_datetime(body, "end_at")
    if not (end_at > start_at):
        raise err(errors.ERR_INVALID_REQUEST, "end_at must be strictly after start_at")
    acuity = require_int(body, "acuity", ge=1, le=5)
    expected_version = require_int(body, "expected_treatment_cycle_version")

    with db.lock:
        # OCC check (priority 5).
        if expected_version != cycle["version"]:
            raise err(errors.ERR_STALE_CYCLE_VERSION,
                      "expected_treatment_cycle_version does not match current cycle version")

        # State (priority 10): chair must be OPEN.
        if chair["status"] != "OPEN":
            raise err(errors.ERR_CHAIR_CLOSED, "Chair is CLOSED")

        # Chair double-booking (priority 11).
        for appt in db.infusion_appointments.values():
            if appt["chair_id"] != chair_id or appt["status"] not in OCCUPYING_STATES:
                continue
            ex_start = parse_datetime(appt["start_at"], "start_at")
            ex_end = parse_datetime(appt["end_at"], "end_at")
            if _overlaps(start_at, end_at, ex_start, ex_end):
                raise err(errors.ERR_CHAIR_DOUBLE_BOOKED,
                          "Chair is double-booked over the requested interval")

        # Nurse acuity capacity (priority 12). Strict > triggers rejection.
        concurrent_load = acuity
        for appt in db.infusion_appointments.values():
            if appt["nurse_id"] != nurse_id or appt["status"] not in OCCUPYING_STATES:
                continue
            ex_start = parse_datetime(appt["start_at"], "start_at")
            ex_end = parse_datetime(appt["end_at"], "end_at")
            if _overlaps(start_at, end_at, ex_start, ex_end):
                concurrent_load += appt["acuity"]
        if concurrent_load > nurse["max_acuity_load"]:
            raise err(errors.ERR_NURSE_ACUITY_EXCEEDED,
                      "Nurse acuity capacity exceeded")

        entity = make_common()
        entity.update({
            "treatment_cycle_id": cycle_id,
            "chair_id": chair_id,
            "nurse_id": nurse_id,
            "start_at": body["start_at"],
            "end_at": body["end_at"],
            "acuity": acuity,
            "status": "SCHEDULED",
        })
        db.infusion_appointments[entity["id"]] = entity
        return success(public(entity), status=201)


@bp.route("/infusion-appointments", methods=["GET"])
def list_appointments():
    _, role = get_auth()
    require_roles(role, ALL_ROLES)
    limit, offset = get_pagination()
    cycle_id = request.args.get("treatment_cycle_id")
    chair_id = request.args.get("chair_id")
    nurse_id = request.args.get("nurse_id")
    items = []
    for a in db.infusion_appointments.values():
        if cycle_id is not None and a["treatment_cycle_id"] != cycle_id:
            continue
        if chair_id is not None and a["chair_id"] != chair_id:
            continue
        if nurse_id is not None and a["nurse_id"] != nurse_id:
            continue
        items.append(a)
    items = sort_by_created(items)
    total = len(items)
    window = [public(a) for a in paginate(items, limit, offset)]
    return list_success(window, limit, offset, total)


@bp.route("/infusion-appointments/<aid>", methods=["GET"])
def get_one_appointment(aid):
    _, role = get_auth()
    require_roles(role, ALL_ROLES)
    entity = get_appointment(aid)
    return success(public(entity), status=200)


@bp.route("/infusion-appointments/<aid>/check-in", methods=["POST"])
def check_in_appointment(aid):
    _, role = get_auth()
    require_roles(role, {"Nurse"})
    appt = get_appointment(aid)
    with db.lock:
        if appt["status"] != "SCHEDULED":
            raise err(errors.ERR_APPOINTMENT_NOT_SCHEDULED, "Appointment is not SCHEDULED")
        cycle = db.treatment_cycles.get(appt["treatment_cycle_id"])
        if cycle["status"] != "ACTIVE":
            raise err(errors.ERR_CYCLE_NOT_ACTIVE, "Parent cycle is not ACTIVE")
        appt["status"] = "CHECKED_IN"
        touch(appt, bump_version=True)
        return success(public(appt), status=200)


@bp.route("/infusion-appointments/<aid>/complete", methods=["POST"])
def complete_appointment(aid):
    _, role = get_auth()
    require_roles(role, {"Nurse"})
    appt = get_appointment(aid)
    with db.lock:
        if appt["status"] != "CHECKED_IN":
            raise err(errors.ERR_APPOINTMENT_NOT_CHECKED_IN, "Appointment is not CHECKED_IN")
        appt["status"] = "COMPLETED"
        touch(appt, bump_version=True)
        return success(public(appt), status=200)


@bp.route("/infusion-appointments/<aid>/cancel", methods=["POST"])
def cancel_appointment(aid):
    _, role = get_auth()
    require_roles(role, {"Nurse", "Pharmacist"})
    appt = get_appointment(aid)
    with db.lock:
        if appt["status"] not in ("SCHEDULED", "CHECKED_IN"):
            raise err(errors.ERR_APPOINTMENT_TERMINAL, "Appointment is in a terminal state")
        appt["status"] = "CANCELLED"
        touch(appt, bump_version=True)
        return success(public(appt), status=200)
