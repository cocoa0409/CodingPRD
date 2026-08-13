"""RestorationTask endpoints: create, work/complete (warranty window opens),
accept, warranty claim (within warranty), warranty rework."""

from __future__ import annotations

from flask import Blueprint

import db
from db import touch, stamp_new
from errors import (
    raise_err,
    ERR_VALIDATION,
    ERR_INVALID_STATE,
    ERR_WARRANTY_EXPIRED,
)
from middleware import require_roles, forbid
from response import success_object, success_list
from services import domain
from services.serializers import restoration_task_view
from util import (
    get_json_body,
    get_or_404,
    parse_iso8601,
    parse_pagination,
    paginate,
    query_arg,
    require_enum,
    require_field,
    require_string,
    sort_created,
)

bp = Blueprint("restoration_tasks", __name__, url_prefix="/api/restoration-tasks")

PM = "ProgramManager"
CC = "ConversionContractor"
ANY = "Any"

TASK_TYPES = {"HARDSCAPE", "LANDSCAPE", "IRRIGATION"}
TRANSITION_TARGETS = {"IN_WORK", "COMPLETE", "ACCEPTED", "WARRANTY_CLAIM"}


@bp.route("", methods=["POST"])
@require_roles(CC, PM)
def create_restoration_task(_user_id: str, _role: str):
    body = get_json_body()
    if body.get("trench_segment_id") is not None:
        get_or_404(db.segments, body["trench_segment_id"], "TrenchSegment")
    if body.get("parcel_id") is not None:
        get_or_404(db.parcels, body["parcel_id"], "Parcel")
    segment_id = require_string(body, "trench_segment_id")
    parcel_id = require_string(body, "parcel_id")
    task_type = require_enum(body, "task_type", TASK_TYPES)

    task = stamp_new({
        "trench_segment_id": segment_id,
        "parcel_id": parcel_id,
        "task_type": task_type,
        "status": "OPEN",
        "completed_on": None,
        "accepted_on": None,
        "warranty_expires_on": None,
    })
    db.restoration_tasks[task["id"]] = task
    return success_object(restoration_task_view(task), 201)


@bp.route("", methods=["GET"])
@require_roles(ANY)
def list_restoration_tasks(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = list(db.restoration_tasks.values())
    segment_id = query_arg("trench_segment_id")
    parcel_id = query_arg("parcel_id")
    status = query_arg("status")
    if segment_id:
        items = [t for t in items if t["trench_segment_id"] == segment_id]
    if parcel_id:
        items = [t for t in items if t["parcel_id"] == parcel_id]
    if status:
        items = [t for t in items if t["status"] == status]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([restoration_task_view(t) for t in page], limit, offset, total)


@bp.route("/<tid>", methods=["GET"])
@require_roles(ANY)
def get_restoration_task(tid: str, _user_id: str, _role: str):
    return success_object(restoration_task_view(get_or_404(db.restoration_tasks, tid,
                                                           "RestorationTask")))


@bp.route("/<tid>/transition", methods=["POST"])
@require_roles(CC, PM)
def transition_restoration_task(tid: str, _user_id: str, _role: str):
    task = get_or_404(db.restoration_tasks, tid, "RestorationTask")
    body = get_json_body()
    to = require_field(body, "to")
    if not isinstance(to, str) or to not in TRANSITION_TARGETS:
        raise_err(ERR_VALIDATION, f"to must be one of {sorted(TRANSITION_TARGETS)}")

    # Per-transition actors: the contractor works and completes; the program
    # manager accepts and raises warranty claims.
    if to in {"IN_WORK", "COMPLETE"} and _role != CC:
        forbid("only ConversionContractor may work or complete a task")
    if to in {"ACCEPTED", "WARRANTY_CLAIM"} and _role != PM:
        forbid("only ProgramManager may accept or claim warranty on a task")

    current = task["status"]

    if to == "IN_WORK":
        if current not in {"OPEN", "WARRANTY_CLAIM"}:
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> IN_WORK")
        task["status"] = "IN_WORK"

    elif to == "COMPLETE":
        if current != "IN_WORK":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> COMPLETE")
        task["completed_on"] = domain.clock_str()
        task["warranty_expires_on"] = domain.clock_plus_days(domain.WARRANTY_DAYS)
        task["status"] = "COMPLETE"

    elif to == "ACCEPTED":
        if current != "COMPLETE":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> ACCEPTED")
        task["accepted_on"] = domain.clock_str()
        task["status"] = "ACCEPTED"

    elif to == "WARRANTY_CLAIM":
        if current != "ACCEPTED":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> WARRANTY_CLAIM")
        # The expiry instant itself is still claimable (clock <= expiry).
        if domain.clock_dt() > parse_iso8601(task["warranty_expires_on"]):
            raise_err(ERR_WARRANTY_EXPIRED, "warranty has expired")
        task["status"] = "WARRANTY_CLAIM"

    touch(task)
    return success_object(restoration_task_view(task))
