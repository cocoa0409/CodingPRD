"""Special-education service continuation during homebound status (PRD §3.9)."""

from flask import Blueprint

import db
import middleware
from errors import ApiError
from middleware import endpoint
from routes import CONTINUATION_STATUSES, IN_SERVICE, SERVICE_TYPES, listing
from services import logic

bp = Blueprint("sped_service_logs", __name__)

READ_ROLES = ["ProgramAdministrator", "CaseManager", "HomeboundTeacher"]

# The four declared continuation transitions; no self-transition is permitted.
CONTINUATION_TRANSITIONS = {
    "CONTINUED": ("MODIFIED_VIRTUAL", "SUSPENDED_PENDING_IEP"),
    "MODIFIED_VIRTUAL": ("SUSPENDED_PENDING_IEP", "CONTINUED"),
    "SUSPENDED_PENDING_IEP": ("CONTINUED",),
}

CREATE_BODY = {
    "case_id": {"type": "string", "required": True},
    "service_type": {"type": "string", "required": True, "enum": SERVICE_TYPES},
    "required_weekly_minutes": {"type": "integer", "required": True, "min": 1},
}

DELIVERY_BODY = {
    "minutes": {"type": "integer", "required": True, "min": 0},
    "service_date": {"type": "date", "required": True},
}

CONTINUATION_BODY = {
    "to_status": {"type": "string", "required": True, "enum": CONTINUATION_STATUSES},
    "continuation_reason": {"type": "string", "required": True},
}

LIST_QUERY = {
    "case_id": {"type": "string"},
    "service_type": {"type": "string", "enum": SERVICE_TYPES},
    "continuation_status": {"type": "string", "enum": CONTINUATION_STATUSES},
}


def load_log(log_id):
    row = db.get("sped_service_logs", log_id)
    if row is None:
        raise ApiError("ERR_SPED_LOG_NOT_FOUND")
    return row


@bp.post("/hhi/sped-service-logs")
@endpoint(["CaseManager"], body=CREATE_BODY, status=201)
def create_log():
    body = middleware.body()

    case = db.get("cases", body["case_id"])                       # tier 5
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND")

    if case["service_status"] not in IN_SERVICE:                  # tier 8
        raise ApiError("ERR_CASE_NOT_ACTIVE")

    for other in db.by_case("sped_service_logs", case["id"]):     # tier 11
        if other["service_type"] == body["service_type"]:
            raise ApiError("ERR_DUPLICATE_SPED_SERVICE_TYPE")

    row = db.insert(
        "sped_service_logs",
        {
            "case_id": case["id"],
            "service_type": body["service_type"],
            "required_weekly_minutes": body["required_weekly_minutes"],
            "delivered_cumulative_minutes": 0,
            "continuation_status": "CONTINUED",
            "compensatory_minutes_owed": 0,
            "last_service_date": None,
            "continuation_reason": None,
        },
    )
    logic.recompute_compensatory_minutes(row, case)
    return middleware.obj(row)


@bp.get("/hhi/sped-service-logs/<log_id>")
@endpoint(READ_ROLES)
def read_log(log_id):
    return middleware.obj(load_log(log_id))


@bp.get("/hhi/sped-service-logs")
@endpoint(READ_ROLES, query=LIST_QUERY)
def list_logs():
    return listing("sped_service_logs", LIST_QUERY)


@bp.post("/hhi/sped-service-logs/<log_id>/record-delivery")
@endpoint(["CaseManager", "HomeboundTeacher"], body=DELIVERY_BODY)
def record_delivery(log_id):
    log = load_log(log_id)
    if log["continuation_status"] == "SUSPENDED_PENDING_IEP":      # tier 12
        raise ApiError("ERR_SPED_SERVICE_SUSPENDED")

    body = middleware.body()
    db.set_field(
        log,
        "delivered_cumulative_minutes",
        log["delivered_cumulative_minutes"] + body["minutes"],
    )
    db.set_field(log, "last_service_date", body["service_date"])
    logic.recompute_compensatory_minutes(log, db.get("cases", log["case_id"]))
    return middleware.obj(log)


@bp.post("/hhi/sped-service-logs/<log_id>/continuation")
@endpoint(["CaseManager"], body=CONTINUATION_BODY)
def change_continuation(log_id):
    log = load_log(log_id)
    body = middleware.body()
    if body["to_status"] not in CONTINUATION_TRANSITIONS[log["continuation_status"]]:
        raise ApiError("ERR_SPED_CONTINUATION_INVALID")            # tier 8

    db.set_field(log, "continuation_status", body["to_status"])
    db.set_field(log, "continuation_reason", body["continuation_reason"])
    logic.recompute_compensatory_minutes(log, db.get("cases", log["case_id"]))
    return middleware.obj(log)
