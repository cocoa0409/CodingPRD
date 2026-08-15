"""Communication log reads and the process-due batch."""

from flask import Blueprint, request

import errors
from db import db
from middleware import authenticate, require_role
from response import success_list, success_object
from serializers import serialize_communication_log
from services.batch import run_process_due
from validators import get_json_body_optional, opt_query_enum, pagination_params

bp = Blueprint("comms", __name__)

LOG_STATUSES = {"QUEUED", "SENT", "FAILED"}
COMM_READ_ROLES = ["OpsAdmin", "ReaccommodationAgent", "DutyManager"]


@bp.get("/irops/communication-logs/<lid>")
def get_log(lid):
    caller = authenticate()
    require_role(caller, COMM_READ_ROLES)
    log = db.communication_logs.get(lid)
    if log is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "CommunicationLog not found")
    return success_object(serialize_communication_log(log), 200)


@bp.get("/irops/communication-logs")
def list_logs():
    caller = authenticate()
    require_role(caller, COMM_READ_ROLES)
    booking_id = request.args.get("booking_id")
    event_id = request.args.get("disruption_event_id")
    status = opt_query_enum("log_status", LOG_STATUSES)
    limit, offset = pagination_params()
    items = sorted(db.communication_logs.values(), key=lambda l: l["created_at"])
    if booking_id is not None:
        items = [l for l in items if l["booking_id"] == booking_id]
    if event_id is not None:
        items = [l for l in items if l["disruption_event_id"] == event_id]
    if status is not None:
        items = [l for l in items if l["log_status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_communication_log(l) for l in page], limit, offset, total)


@bp.post("/irops/communications/process-due")
def process_due():
    caller = authenticate()
    require_role(caller, ["OpsAdmin"])
    get_json_body_optional()
    counts = run_process_due()
    return success_object(counts, 200)
