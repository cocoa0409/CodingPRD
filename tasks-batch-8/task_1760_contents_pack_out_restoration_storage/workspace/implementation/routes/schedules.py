"""PackBackSchedule endpoints."""

from flask import Blueprint

from db import store
from errors import (
    validation,
    invalid_transition,
    window_invalid,
    job_not_ready_for_packback,
    crew_window_overlap,
    no_eligible_items,
    open_claim_blocks_packback,
)
from helpers import (
    get_body,
    require_string,
    require_enum,
    require_int,
    require_date,
    make_common_fields,
    get_job,
    get_schedule,
    touch,
    items_of_job,
    parse_date_str,
)
from middleware import require_roles
from response import success_object, success
from services.cascade import release_active_placement
from services.recompute import recompute_room

bp = Blueprint("schedules", __name__)

SCHEDULE_ACTIONS = {"CONFIRM", "START_TRANSIT", "DELIVER", "COMPLETE", "RESCHEDULE", "CANCEL"}
OPEN_CLAIM_STATUSES = {"FILED", "UNDER_REVIEW", "APPROVED"}


def serialize_schedule(s):
    return dict(s)


def eligible_items_of_job(job_id):
    """Items of the job with processing_status IN_STORAGE and all referrals QA_ACCEPTED."""
    result = []
    for item in items_of_job(job_id):
        if item["processing_status"] != "IN_STORAGE":
            continue
        referrals = [r for r in store.referrals.values() if r["item_id"] == item["id"]]
        if all(r["status"] == "QA_ACCEPTED" for r in referrals):
            result.append(item)
    return result


def _validate_window(start_hour, end_hour):
    if not isinstance(start_hour, int) or isinstance(start_hour, bool):
        raise validation("window_start_hour must be an integer")
    if not isinstance(end_hour, int) or isinstance(end_hour, bool):
        raise validation("window_end_hour must be an integer")
    if start_hour < 0 or start_hour > 23:
        raise validation("window_start_hour must be in 0..23")
    if end_hour < 1 or end_hour > 24:
        raise validation("window_end_hour must be in 1..24")
    if end_hour <= start_hour:
        raise window_invalid()


@bp.route("/api/pack-out-jobs/<job_id>/pack-back-schedules", methods=["POST"])
def create_schedule(job_id):
    user_id, role = require_roles("ProjectManager")
    body = get_body()
    crew_id = require_string(body, "crew_id")
    service_date = require_date(body, "service_date")
    window_start = body.get("window_start_hour")
    window_end = body.get("window_end_hour")
    if window_start is None:
        raise validation("window_start_hour is required")
    if window_end is None:
        raise validation("window_end_hour is required")
    _validate_window(window_start, window_end)

    job = get_job(job_id)
    if job["status"] == "CLOSED":
        raise invalid_transition("Job is CLOSED")

    sched = make_common_fields()
    sched.update({
        "job_id": job["id"],
        "crew_id": crew_id,
        "service_date": service_date,
        "window_start_hour": window_start,
        "window_end_hour": window_end,
        "status": "REQUESTED",
        "eligible_item_count": None,
        "reschedule_count": 0,
    })
    store.schedules[sched["id"]] = sched
    return success_object(serialize_schedule(sched), status=201)


@bp.route("/api/pack-out-jobs/<job_id>/pack-back-schedules", methods=["GET"])
def list_schedules(job_id):
    user_id, role = require_roles("ProjectManager", "InventoryTechnician")
    job = get_job(job_id)
    scheds = [s for s in store.schedules.values() if s["job_id"] == job["id"]]
    scheds.sort(key=lambda s: s["created_at"])
    return success([serialize_schedule(s) for s in scheds], status=200, response_type="array")


@bp.route("/api/pack-back-schedules/<sched_id>/transition", methods=["POST"])
def transition_schedule(sched_id):
    user_id, role = require_roles("ProjectManager")
    body = get_body()
    action = require_enum(body, "action", SCHEDULE_ACTIONS)
    sched = get_schedule(sched_id)
    job = store.jobs.get(sched["job_id"])

    if action == "CONFIRM":
        if sched["status"] != "REQUESTED":
            raise invalid_transition("Schedule is not REQUESTED")
        if job is None or job["structure_status"] != "COMPLETE":
            raise job_not_ready_for_packback()
        # crew window overlap among CONFIRMED / IN_TRANSIT with same crew_id + service_date
        for other in store.schedules.values():
            if other["id"] == sched["id"]:
                continue
            if other["crew_id"] != sched["crew_id"]:
                continue
            if other["service_date"] != sched["service_date"]:
                continue
            if other["status"] not in ("CONFIRMED", "IN_TRANSIT"):
                continue
            # half-open [start, end) overlap: overlap iff start < other_end and other_start < end
            if sched["window_start_hour"] < other["window_end_hour"] and other["window_start_hour"] < sched["window_end_hour"]:
                raise crew_window_overlap()
        eligible = eligible_items_of_job(job["id"])
        if len(eligible) < 1:
            raise no_eligible_items()
        for item in eligible:
            for c in store.claims.values():
                if c["item_id"] == item["id"] and c["status"] in OPEN_CLAIM_STATUSES:
                    raise open_claim_blocks_packback()
        sched["eligible_item_count"] = len(eligible)
        sched["status"] = "CONFIRMED"
        touch(sched)
    elif action == "START_TRANSIT":
        if sched["status"] != "CONFIRMED":
            raise invalid_transition("Schedule is not CONFIRMED")
        sched["status"] = "IN_TRANSIT"
        touch(sched)
        # sweep eligible items
        if job is not None:
            eligible = eligible_items_of_job(job["id"])
            for item in eligible:
                item["processing_status"] = "PACKED_BACK"
                touch(item)
                release_active_placement(item, "PACK_BACK")
                room = store.rooms.get(item["room_id"])
                if room is not None:
                    recompute_room(room)
                    touch(room)
            # first IN_TRANSIT schedule moves job ACTIVE -> PACKBACK_IN_PROGRESS
            if job["status"] == "ACTIVE":
                job["status"] = "PACKBACK_IN_PROGRESS"
                touch(job)
    elif action == "DELIVER":
        if sched["status"] != "IN_TRANSIT":
            raise invalid_transition("Schedule is not IN_TRANSIT")
        sched["status"] = "DELIVERED"
        touch(sched)
        if job is not None:
            for item in items_of_job(job["id"]):
                if item["processing_status"] == "PACKED_BACK":
                    item["processing_status"] = "DELIVERED"
                    touch(item)
                    room = store.rooms.get(item["room_id"])
                    if room is not None:
                        recompute_room(room)
                        touch(room)
    elif action == "COMPLETE":
        if sched["status"] != "DELIVERED":
            raise invalid_transition("Schedule is not DELIVERED")
        sched["status"] = "COMPLETED"
        touch(sched)
    elif action == "RESCHEDULE":
        if sched["status"] != "CONFIRMED":
            raise invalid_transition("Schedule is not CONFIRMED")
        service_date = body.get("service_date")
        window_start = body.get("window_start_hour")
        window_end = body.get("window_end_hour")
        if service_date is None or window_start is None or window_end is None:
            raise validation("service_date, window_start_hour, window_end_hour are required")
        if not isinstance(service_date, str):
            raise validation("service_date must be a string")
        try:
            parse_date_str(service_date)
        except Exception:
            raise validation("service_date must be YYYY-MM-DD")
        _validate_window(window_start, window_end)
        sched["service_date"] = service_date
        sched["window_start_hour"] = window_start
        sched["window_end_hour"] = window_end
        sched["status"] = "REQUESTED"
        sched["reschedule_count"] += 1
        touch(sched)
    elif action == "CANCEL":
        if sched["status"] not in ("REQUESTED", "CONFIRMED"):
            raise invalid_transition("Schedule cannot be CANCELLED from current status")
        sched["status"] = "CANCELLED"
        touch(sched)
    return success_object(serialize_schedule(sched))
