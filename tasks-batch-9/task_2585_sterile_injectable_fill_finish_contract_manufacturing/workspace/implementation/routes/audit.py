"""/audit-engagements and the logical clock control."""

from flask import Blueprint, request

import calc
import serialize
import services
from auth import endpoint
from common import CLOCK, ApiError, clock_now
from listing import object_response
from store import DB, new_row, set_raw, touch
from validate import (
    AUDIT_KINDS,
    HOST_OUTCOMES,
    f_dt,
    f_enum,
    f_int,
    f_str,
    parse_body,
)

bp = Blueprint("audit", __name__)

ENGAGEMENT_FIELDS = [
    f_str("client_project_id", 1, None),
    f_enum("audit_kind", AUDIT_KINDS),
    f_dt("requested_window_start"),
]


@bp.post("/audit-engagements")
@endpoint(["ClientRepresentative", "ProgramManager"], crep_scope="project_body")
def create_engagement():
    body = parse_body(request.get_json(silent=True), ENGAGEMENT_FIELDS)
    project = services.require("project", body["client_project_id"])
    if body["requested_window_start"] <= clock_now():
        raise ApiError(
            "ERR_INVALID_WINDOW",
            422,
            "requested_window_start must be strictly later than the logical clock.",
        )
    row = new_row(
        {
            "client_project_id": project["id"],
            "audit_kind": body["audit_kind"],
            "requested_window_start": body["requested_window_start"],
            "status": "REQUESTED",
            "finding_count": 0,
            "hosted_at": None,
        }
    )
    set_raw(row, "requested_window_start", body["_raw_requested_window_start"])
    DB.engagements[row["id"]] = row
    return object_response(serialize.engagement_out(row), 201)


@bp.post("/audit-engagements/<engagement_id>/host")
@endpoint(["ProgramManager"])
def host_engagement(engagement_id):
    engagement = services.require("engagement", engagement_id)
    body = parse_body(
        request.get_json(silent=True),
        [f_enum("outcome", HOST_OUTCOMES), f_int("finding_count", 0)],
    )
    if engagement["status"] == "HOSTED":
        raise services.state_conflict(
            "ERR_AUDIT_ENGAGEMENT_STATE_INVALID", "HOSTED is terminal."
        )
    if body["outcome"] == "HOSTED":
        project = DB.projects.get(engagement["client_project_id"])
        if project is None or project["status"] != "ACTIVE":
            raise services.state_conflict(
                "ERR_PROJECT_STATE_INVALID", "Hosting requires an ACTIVE project."
            )
        suite = DB.suites.get(project["primary_suite_id"])
        if suite is not None and calc.suite_posture(suite) == "FROZEN":
            raise services.state_conflict(
                "ERR_SUITE_NOT_OPEN",
                "A sponsor is not walked through a frozen suite.",
            )
        engagement["finding_count"] = body["finding_count"]
        engagement["hosted_at"] = clock_now()
        engagement["status"] = "HOSTED"
    else:
        engagement["status"] = "DEFERRED"
    touch(engagement)
    return object_response(serialize.engagement_out(engagement))


@bp.post("/_clock/set_current_utc")
@endpoint(
    [
        "ProgramManager",
        "QaReviewer",
        "MicrobiologyAnalyst",
        "ProductionSupervisor",
        "QualifiedPerson",
    ]
)
def set_clock():
    body = parse_body(request.get_json(silent=True), [f_dt("to_iso8601")])
    new_now = body["to_iso8601"]
    CLOCK.set(new_now, body["_raw_to_iso8601"])
    lapsed, expired = services.apply_clock_move(new_now)
    return object_response(
        {
            "current_utc": body["_raw_to_iso8601"],
            "lapsed_qualification_count": lapsed,
            "expired_component_lot_count": expired,
        }
    )
