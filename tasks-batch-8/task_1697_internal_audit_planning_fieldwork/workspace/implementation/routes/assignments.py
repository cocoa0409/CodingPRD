"""EngagementAssignment endpoints (PRD 3.4): staffing with duplicate and
half-open-overlap integrity rules; cancellation releases reserved hours."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_ASSIGNMENT_INVALID_STATE,
    ERR_ASSIGNMENT_OVERLAP,
    ERR_ASSIGNMENT_WINDOW_INVALID,
    ERR_AUDITOR_INACTIVE,
    ERR_DUPLICATE_ASSIGNMENT,
    ERR_ENGAGEMENT_INVALID_STATE,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, query_str
from services.cascades import recompute_engagement_reserved
from services.core import new_record, public, touch
from util import parse_dt
from validate import (
    body_ref,
    check_unknown_fields,
    get_body,
    req_datetime,
    req_enum,
    req_number,
    req_str,
    require_path,
)

bp = Blueprint("engagement_assignments", __name__)

CREATE_FIELDS = {
    "engagement_id", "auditor_id", "role_in_engagement",
    "start_date", "end_date", "allocated_hours",
}
ROLES_IN_ENGAGEMENT = ("LEAD", "STAFF", "REVIEWER")
WORKING_ENGAGEMENT_STATUSES = ("PLANNED", "SCOPED", "FIELDWORK")


@bp.post("/audit/engagement-assignments")
def create_assignment():
    authorized(["AuditManager"])
    body = get_body()
    # Stage 4: body FK existence in declared input order
    body_ref(body, "engagement_id", "engagements")
    body_ref(body, "auditor_id", "auditors")
    # Stage 5: shape
    check_unknown_fields(body, CREATE_FIELDS)
    engagement_id = req_str(body, "engagement_id")
    auditor_id = req_str(body, "auditor_id")
    role_in_engagement = req_enum(body, "role_in_engagement", ROLES_IN_ENGAGEMENT)
    start_date = req_datetime(body, "start_date")
    end_date = req_datetime(body, "end_date")
    allocated_hours = req_number(body, "allocated_hours", positive=True)
    eng = db["engagements"][engagement_id]
    auditor = db["auditors"][auditor_id]
    # Stage 7: engagement must be in a working state; auditor must be ACTIVE
    if eng["status"] not in WORKING_ENGAGEMENT_STATUSES:
        raise_error(ERR_ENGAGEMENT_INVALID_STATE,
                    f"staffing changes require PLANNED/SCOPED/FIELDWORK, not {eng['status']}")
    if auditor["status"] != "ACTIVE":
        raise_error(ERR_AUDITOR_INACTIVE, "cannot assign an INACTIVE auditor")
    # Stage 9: duplicate ACTIVE assignment of the same auditor on the engagement
    for a in db["engagement_assignments"].values():
        if (a["auditor_id"] == auditor_id and a["engagement_id"] == engagement_id
                and a["status"] == "ACTIVE"):
            raise_error(ERR_DUPLICATE_ASSIGNMENT,
                        "auditor already holds an ACTIVE assignment on this engagement")
    # Stage 9: half-open window overlap — [start,end) collides iff
    # other.start < new.end AND new.start < other.end; touching windows allowed.
    new_start = parse_dt(start_date)
    new_end = parse_dt(end_date)
    for a in db["engagement_assignments"].values():
        if a["auditor_id"] != auditor_id or a["status"] != "ACTIVE":
            continue
        other_start = parse_dt(a["start_date"])
        other_end = parse_dt(a["end_date"])
        if other_start < new_end and new_start < other_end:
            raise_error(ERR_ASSIGNMENT_OVERLAP,
                        "window collides with another ACTIVE assignment of the auditor")
    # Stage 10: temporal — end strictly after start
    if not new_end > new_start:
        raise_error(ERR_ASSIGNMENT_WINDOW_INVALID, "end_date must be strictly after start_date")
    rec = new_record("engagement_assignments", {
        "engagement_id": engagement_id,
        "auditor_id": auditor_id,
        "role_in_engagement": role_in_engagement,
        "start_date": start_date,
        "end_date": end_date,
        "allocated_hours": allocated_hours,
        "status": "ACTIVE",
    })
    recompute_engagement_reserved(eng)
    touch(eng)
    return success_object(public(rec), status=201)


@bp.get("/audit/engagement-assignments")
def list_assignments():
    filters = {
        "engagement_id": query_str("engagement_id"),
        "auditor_id": query_str("auditor_id"),
        "status": query_str("status"),
    }
    return list_response("engagement_assignments", filters)


@bp.get("/audit/engagement-assignments/<rid>")
def get_assignment(rid):
    return get_one("engagement_assignments", rid)


@bp.post("/audit/engagement-assignments/<rid>/cancel")
def cancel_assignment(rid):
    authorized(["AuditManager"])
    asg = require_path("engagement_assignments", rid)
    # Stage 7: assignment ACTIVE, engagement in a working state
    if asg["status"] != "ACTIVE":
        raise_error(ERR_ASSIGNMENT_INVALID_STATE, "assignment is not ACTIVE")
    eng = db["engagements"][asg["engagement_id"]]
    if eng["status"] not in WORKING_ENGAGEMENT_STATUSES:
        raise_error(ERR_ENGAGEMENT_INVALID_STATE,
                    f"staffing changes require PLANNED/SCOPED/FIELDWORK, not {eng['status']}")
    asg["status"] = "CANCELLED"
    touch(asg)
    # Compensating action: release the reserved hours
    recompute_engagement_reserved(eng)
    touch(eng)
    return success_object(public(asg))
