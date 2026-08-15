"""ExtensionRequest endpoints (PRD §3.7): OCC-guarded create-with-supersede,
coverage and cost-posture gates on approval."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_COC_COVERAGE_GAP,
    ERR_COST_OVERRUN_BLOCKED,
    ERR_EXTENSION_NOT_FORWARD,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_MAX_DURATION_EXCEEDED,
    ERR_STALE_ASSIGNMENT_VERSION,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.core import new_record, program_of_assignment, touch
from validate import (
    get_body, opt_str, req_date, req_field, require_fk, require_path_resource,
)

bp = Blueprint("extension_requests", __name__)


@bp.post("/mobility/extension-requests")
def create_extension_request():
    authorized(["MobilityAdmin"])
    body = get_body()
    asg = require_fk("assignments", req_field(body, "assignment_id"), "assignment_id")
    requested_new_end_date = req_date(body, "requested_new_end_date")
    ev = req_field(body, "expected_assignment_version")
    if isinstance(ev, bool) or not isinstance(ev, int):
        raise_error(ERR_INVALID_REQUEST, "expected_assignment_version must be an integer")
    reason = opt_str(body, "reason", None)
    # State gate (priority 5): the assignment must be ACTIVE.
    if asg["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "extension requests require an ACTIVE assignment")
    # OCC guard (priority 6).
    if ev != asg["version"]:
        raise_error(
            ERR_STALE_ASSIGNMENT_VERSION,
            "expected_assignment_version does not match the assignment's current version",
        )
    # Date-window family (priority 9), pinned order: strictly-forward first,
    # then the duration cap.
    if requested_new_end_date.isoformat() <= asg["planned_end_date"]:
        raise_error(
            ERR_EXTENSION_NOT_FORWARD,
            "requested_new_end_date must be strictly after the current planned_end_date",
        )
    program = program_of_assignment(asg)
    from util import parse_date
    start = parse_date(asg["start_date"])
    if (requested_new_end_date - start).days > program["max_assignment_duration_days"]:
        raise_error(
            ERR_MAX_DURATION_EXCEEDED,
            "the extension would exceed the program's max_assignment_duration_days",
        )
    # Create-with-supersede: any prior PENDING request becomes SUPERSEDED.
    for x in db["extension_requests"].values():
        if x["assignment_id"] == asg["id"] and x["status"] == "PENDING":
            x["status"] = "SUPERSEDED"
            touch(x)
    rec = new_record("extension_requests", {
        "assignment_id": asg["id"],
        "requested_new_end_date": requested_new_end_date.isoformat(),
        "reason": reason,
        "status": "PENDING",
        "decided_by_user_id": None,
    })
    # The superseding create advances the assignment version by exactly one.
    touch(asg)
    return success_object(public(rec), status=201)


@bp.get("/mobility/extension-requests/<rid>")
def get_extension_request(rid):
    return get_one("extension_requests", rid)


@bp.get("/mobility/extension-requests")
def list_extension_requests():
    return list_response("extension_requests", {
        "assignment_id": request.args.get("assignment_id"),
        "status": request.args.get("status"),
    })


@bp.post("/mobility/extension-requests/<rid>/approve")
def approve_extension(rid):
    caller = authorized(["BusinessUnitApprover"])
    x = require_path_resource("extension_requests", rid)
    if x["status"] != "PENDING":
        raise_error(ERR_INVALID_STATE, "only a PENDING extension request can be approved")
    asg = db["assignments"].get(x["assignment_id"])
    if asg is None or asg["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "the assignment must be ACTIVE")
    # Coverage gate (priority 12) precedes the posture gate (priority 13).
    if asg["totalization_applies"]:
        covered = any(
            c["assignment_id"] == asg["id"] and c["status"] == "ISSUED"
            and c["valid_until"] is not None and c["valid_until"] >= x["requested_new_end_date"]
            for c in db["certificates_of_coverage"].values()
        )
        if not covered:
            raise_error(
                ERR_COC_COVERAGE_GAP,
                "certificate coverage must reach the requested new end date",
            )
    if asg["cost_posture"] == "OVERRUN":
        raise_error(ERR_COST_OVERRUN_BLOCKED, "extension approval is blocked while the assignment is in OVERRUN")
    x["status"] = "APPROVED"
    x["decided_by_user_id"] = caller.user_id
    touch(x)
    asg["planned_end_date"] = x["requested_new_end_date"]
    touch(asg)  # refreshed updated_at; version advances by exactly one
    return success_object(public(x))


@bp.post("/mobility/extension-requests/<rid>/decline")
def decline_extension(rid):
    caller = authorized(["BusinessUnitApprover"])
    x = require_path_resource("extension_requests", rid)
    if x["status"] != "PENDING":
        raise_error(ERR_INVALID_STATE, "only a PENDING extension request can be declined")
    asg = db["assignments"].get(x["assignment_id"])
    if asg is None or asg["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "the assignment must be ACTIVE")
    x["status"] = "DECLINED"
    x["decided_by_user_id"] = caller.user_id
    touch(x)
    return success_object(public(x))
