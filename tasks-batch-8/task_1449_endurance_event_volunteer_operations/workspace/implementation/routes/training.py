"""Training record endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import errors
from db import store
from middleware import require_roles
from response import success_object, success_list
from util import (
    get_body, require_field, as_string, as_enum, logical_now, format_iso,
)
from services.core import (
    make_record, touch, paginate, sort_by_created, serialize_training,
    get_event_or_404, get_volunteer_or_404, get_training_or_404,
    TRAINING_VALIDITY_DAYS,
)

bp = Blueprint("training", __name__)
ANY = ("Anonymous", "Volunteer", "Captain", "GroupLeader", "VolunteerCoordinator", "EventDirector")

MODULE_CODES = {"SAFETY_BRIEFING", "MEDICAL_RESPONSE", "CAPTAIN_COURSE"}


@bp.post("/volunteer-ops/training-records")
def create_training():
    require_roles("VolunteerCoordinator")
    body = get_body()
    event_id = as_string(require_field(body, "event_id"), "event_id")
    get_event_or_404(event_id)
    volunteer_id = as_string(require_field(body, "volunteer_id"), "volunteer_id")
    get_volunteer_or_404(volunteer_id)
    module_code = as_enum(require_field(body, "module_code"), "module_code", MODULE_CODES)
    for tr in store.training_records.values():
        if tr["volunteer_id"] == volunteer_id and tr["module_code"] == module_code:
            raise errors.duplicate_training_record()
    rec = make_record({
        "event_id": event_id,
        "volunteer_id": volunteer_id,
        "module_code": module_code,
        "status": "ENROLLED",
        "passed_at": None,
        "valid_until": None,
        "attempt_count": 1,
    })
    store.training_records[rec["id"]] = rec
    return success_object(serialize_training(rec), status=201)


@bp.get("/volunteer-ops/training-records")
def list_training():
    require_roles(*ANY)
    event_id = request.args.get("event_id")
    volunteer_id = request.args.get("volunteer_id")
    items = [
        t for t in store.training_records.values()
        if (event_id is None or t["event_id"] == event_id)
        and (volunteer_id is None or t["volunteer_id"] == volunteer_id)
    ]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serialize_training(t) for t in page], limit, offset, total)


@bp.get("/volunteer-ops/training-records/<trainingRecordId>")
def get_training(trainingRecordId):
    require_roles(*ANY)
    tr = get_training_or_404(trainingRecordId)
    return success_object(serialize_training(tr))


@bp.post("/volunteer-ops/training-records/<trainingRecordId>/pass")
def pass_training(trainingRecordId):
    require_roles("VolunteerCoordinator")
    tr = get_training_or_404(trainingRecordId)
    if tr["status"] != "ENROLLED":
        raise errors.training_invalid_state()
    now = logical_now()
    days = TRAINING_VALIDITY_DAYS[tr["module_code"]]
    tr["status"] = "PASSED"
    tr["passed_at"] = format_iso(now)
    tr["valid_until"] = format_iso(now + timedelta(days=days))
    touch(tr)
    return success_object(serialize_training(tr))


@bp.post("/volunteer-ops/training-records/<trainingRecordId>/fail")
def fail_training(trainingRecordId):
    require_roles("VolunteerCoordinator")
    tr = get_training_or_404(trainingRecordId)
    if tr["status"] != "ENROLLED":
        raise errors.training_invalid_state()
    tr["status"] = "FAILED"
    touch(tr)
    return success_object(serialize_training(tr))


@bp.post("/volunteer-ops/training-records/<trainingRecordId>/re-enroll")
def reenroll_training(trainingRecordId):
    require_roles("VolunteerCoordinator")
    tr = get_training_or_404(trainingRecordId)
    if tr["status"] not in {"FAILED", "EXPIRED"}:
        raise errors.training_invalid_state()
    tr["status"] = "ENROLLED"
    tr["attempt_count"] += 1
    tr["passed_at"] = None
    tr["valid_until"] = None
    touch(tr)
    return success_object(serialize_training(tr))
