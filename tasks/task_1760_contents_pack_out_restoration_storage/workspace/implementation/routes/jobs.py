"""PackOutJob endpoints: create, read, transition (structure + close)."""

from flask import Blueprint

from db import store
from errors import (
    validation,
    invalid_transition,
    job_items_not_terminal,
)
from helpers import (
    get_body,
    require_string,
    require_enum,
    make_common_fields,
    get_job,
    touch,
    items_of_job,
)
from middleware import require_roles, parse_pagination, paginate
from response import success_object, success_list
from services.recompute import job_rooms

bp = Blueprint("jobs", __name__)

COVERAGE_TYPES = {"ACV", "RCV"}
JOB_TRANSITION_ACTIONS = {"STRUCTURE_START", "STRUCTURE_COMPLETE", "STRUCTURE_RESCIND", "CLOSE"}
TERMINAL_ITEM_STATUSES = {"DISPOSED", "DELIVERED", "CLAIM_SETTLED"}


def serialize_job(job):
    return dict(job)


@bp.route("/api/pack-out-jobs", methods=["POST"])
def create_job():
    user_id, role = require_roles("ProjectManager")
    body = get_body()
    claim_number = require_string(body, "claim_number")
    property_address = require_string(body, "property_address")
    carrier_name = require_string(body, "carrier_name")
    policy_coverage_type = require_enum(body, "policy_coverage_type", COVERAGE_TYPES)
    job = make_common_fields()
    job.update({
        "claim_number": claim_number,
        "property_address": property_address,
        "carrier_name": carrier_name,
        "policy_coverage_type": policy_coverage_type,
        "status": "INTAKE",
        "structure_status": "PENDING",
        "billing_status": "ACCUMULATING",
        "accrued_storage_total_cents": 0,
    })
    store.jobs[job["id"]] = job
    return success_object(serialize_job(job), status=201)


@bp.route("/api/pack-out-jobs/<job_id>", methods=["GET"])
def read_job(job_id):
    user_id, role = require_roles(
        "ProjectManager", "InventoryTechnician", "BillingClerk", "ClaimsAdjuster"
    )
    job = get_job(job_id)
    return success_object(serialize_job(job))


@bp.route("/api/pack-out-jobs/<job_id>/transition", methods=["POST"])
def transition_job(job_id):
    user_id, role = require_roles("ProjectManager")
    body = get_body()
    action = require_enum(body, "action", JOB_TRANSITION_ACTIONS)
    job = get_job(job_id)

    if action == "CLOSE":
        if job["status"] == "CLOSED":
            raise invalid_transition("Job already CLOSED")
        if job["status"] not in ("INTAKE", "ACTIVE", "PACKBACK_IN_PROGRESS"):
            raise invalid_transition("Job status does not permit CLOSE")
        items = items_of_job(job["id"])
        if any(i["processing_status"] not in TERMINAL_ITEM_STATUSES for i in items):
            raise job_items_not_terminal()
        for s in store.statements.values():
            if s["job_id"] == job["id"] and s["status"] == "PROVISIONAL":
                raise invalid_transition("Job has a PROVISIONAL statement")
        for inv in store.invoices.values():
            if inv["job_id"] == job["id"] and inv["status"] in ("DRAFT", "SUBMITTED", "DISPUTED"):
                raise invalid_transition("Job has an open invoice")
        job["status"] = "CLOSED"
        touch(job)
        return success_object(serialize_job(job))

    # Structure actions require job not CLOSED
    if job["status"] == "CLOSED":
        raise invalid_transition("Job is CLOSED")

    if action == "STRUCTURE_START":
        if job["structure_status"] != "PENDING":
            raise invalid_transition("structure_status is not PENDING")
        job["structure_status"] = "IN_PROGRESS"
    elif action == "STRUCTURE_COMPLETE":
        if job["structure_status"] != "IN_PROGRESS":
            raise invalid_transition("structure_status is not IN_PROGRESS")
        job["structure_status"] = "COMPLETE"
    elif action == "STRUCTURE_RESCIND":
        if job["structure_status"] != "COMPLETE":
            raise invalid_transition("structure_status is not COMPLETE")
        for sched in store.schedules.values():
            if sched["job_id"] == job["id"] and sched["status"] in ("CONFIRMED", "IN_TRANSIT", "DELIVERED"):
                raise invalid_transition("A live pack-back schedule blocks rescission")
        job["structure_status"] = "IN_PROGRESS"
    touch(job)
    return success_object(serialize_job(job))


# ---- Rooms ----

ROOM_TYPES = {"LIVING", "BEDROOM", "KITCHEN", "BATH", "GARAGE", "BASEMENT", "OTHER"}


def serialize_room(room):
    return dict(room)


@bp.route("/api/pack-out-jobs/<job_id>/rooms", methods=["POST"])
def create_room(job_id):
    user_id, role = require_roles("ProjectManager")
    body = get_body()
    from helpers import require_int, optional_int
    name = require_string(body, "name")
    room_type = require_enum(body, "room_type", ROOM_TYPES)
    floor_level = optional_int(body, "floor_level", default=1)
    job = get_job(job_id)
    if job["status"] == "CLOSED":
        raise invalid_transition("Job is CLOSED")
    room = make_common_fields()
    room.update({
        "job_id": job["id"],
        "name": name,
        "floor_level": floor_level,
        "room_type": room_type,
        "status": "OPEN",
        "item_count": 0,
    })
    store.rooms[room["id"]] = room
    return success_object(serialize_room(room), status=201)


@bp.route("/api/pack-out-jobs/<job_id>/rooms", methods=["GET"])
def list_rooms(job_id):
    user_id, role = require_roles(
        "ProjectManager", "InventoryTechnician", "BillingClerk", "ClaimsAdjuster"
    )
    job = get_job(job_id)
    limit, offset = parse_pagination()
    rooms = job_rooms(job["id"])
    page, total = paginate([serialize_room(r) for r in rooms], limit, offset)
    return success_list(page, limit, offset, total)
