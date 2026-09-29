"""Repair-deadline extension requests (PRD 3.6)."""
from flask import Blueprint, request

import constants
import db
import response
import util
import validate
from errors import ApiError
from middleware import COMPLIANCE_MANAGER, REGULATOR, endpoint, read_endpoint
from services import deadlines, guards, posture

bp = Blueprint("extension_requests", __name__)


def _reason_applicable(reason_code, system):
    if reason_code == "INDUSTRIAL_PROCESS_SHUTDOWN_REQUIRED":
        return system["system_category"] == "INDUSTRIAL_PROCESS_REFRIGERATION"
    if reason_code == "PERMIT_PENDING":
        return any(
            plan["system_id"] == system["id"]
            and plan["status"] in ("APPROVED", "IN_PROGRESS")
            for plan in db.values("retrofit_plans")
        )
    return True


@bp.post("/extension-requests")
@endpoint([COMPLIANCE_MANAGER])
def create_extension_request():
    payload = validate.body()
    leak_event_id = validate.req_id(payload, "leak_event_id")
    reason_code = validate.req_enum(payload, "reason_code",
                                    constants.EXTENSION_REASON_CODES)
    requested_days = validate.req_int(payload, "requested_days", minimum=1,
                                      maximum=constants.MAX_REQUESTED_EXTENSION_DAYS)
    justification = validate.req_str(payload, "justification", min_length=10)
    event = db.require("leak_events", leak_event_id)
    guards.require_event_not_terminal(event)
    system = db.require("systems", event["system_id"])
    if not _reason_applicable(reason_code, system):
        raise ApiError("ERR_EXTENSION_REASON_NOT_APPLICABLE")
    clock = db.now()
    if deadlines.is_overdue(event["repair_deadline"], clock):
        raise ApiError("ERR_EXTENSION_WINDOW_CLOSED")

    extension = db.new_entity()
    extension.update({
        "leak_event_id": event["id"],
        "reason_code": reason_code,
        "requested_days": requested_days,
        "justification": justification,
        "granted_days": None,
        "status": "PENDING",
        "requested_at": clock,
        "expires_at": util.add_days(clock, constants.EXTENSION_DECISION_WINDOW_DAYS),
        "decided_at": None,
        "revoked_at": None,
        "revocation_reason_code": None,
        "deadline_before": event["repair_deadline"],
        "deadline_after": None,
    })
    db.insert("extension_requests", extension)
    return response.created(extension)


@bp.get("/extension-requests")
@read_endpoint
def list_extension_requests():
    filters = {
        "leak_event_id": request.args.get("leak_event_id"),
        "status": request.args.get("status"),
        "reason_code": request.args.get("reason_code"),
    }
    return response.listing(db.values("extension_requests"), filters)


@bp.get("/extension-requests/<extension_id>")
@read_endpoint
def get_extension_request(extension_id):
    return response.ok(db.require("extension_requests", extension_id))


@bp.post("/extension-requests/<extension_id>/decision")
@endpoint([REGULATOR])
def decide_extension_request(extension_id):
    payload = validate.body()
    decision = validate.req_enum(payload, "decision", ("APPROVE", "DENY"))
    granted_days = None
    if decision == "APPROVE":
        granted_days = validate.req_int(payload, "granted_days", minimum=1)
    else:
        validate.req_str(payload, "denial_reason_code")
    extension = db.require("extension_requests", extension_id)
    guards.require_state(extension["status"] == "PENDING")
    clock = db.now()
    if clock > extension["expires_at"]:
        raise ApiError("ERR_EXTENSION_WINDOW_CLOSED")
    event = db.require("leak_events", extension["leak_event_id"])

    snap = db.snapshot(extension)
    if decision == "DENY":
        extension["status"] = "DENIED"
        extension["decided_at"] = clock
        db.commit(extension, snap)
        return response.ok(extension)

    # PRD 3.6 pins this order for an approval.
    if granted_days > extension["requested_days"]:
        raise ApiError("ERR_GRANTED_DAYS_EXCEED_REQUESTED")
    if granted_days > event["extension_days_remaining"]:
        raise ApiError("ERR_EXTENSION_DAY_CAP_EXCEEDED")
    guards.require_event_not_terminal(event)

    extension["status"] = "APPROVED"
    extension["granted_days"] = granted_days
    extension["decided_at"] = clock
    event_snap = db.snapshot(event)
    new_deadline = deadlines.recompute_extension_budget(event)
    extension["deadline_after"] = new_deadline
    if event["status"] == "REPAIR_OVERDUE" and not deadlines.is_overdue(new_deadline, clock):
        event["status"] = "OPEN"
    db.commit(event, event_snap)
    db.commit(extension, snap)
    system = db.require("systems", event["system_id"])
    posture.recompute_store_by_id(system["store_id"])
    return response.ok(extension)


@bp.post("/extension-requests/<extension_id>/revocation")
@endpoint([REGULATOR])
def revoke_extension_request(extension_id):
    payload = validate.body()
    revocation_reason_code = validate.req_str(payload, "revocation_reason_code")
    extension = db.require("extension_requests", extension_id)
    guards.require_state(extension["status"] == "APPROVED")
    event = db.require("leak_events", extension["leak_event_id"])
    guards.require_event_not_terminal(event)

    clock = db.now()
    snap = db.snapshot(extension)
    extension["status"] = "REVOKED"
    extension["revoked_at"] = clock
    extension["revocation_reason_code"] = revocation_reason_code
    event_snap = db.snapshot(event)
    deadlines.recompute_extension_budget(event)
    # PRD 3.6: the deadline returns to exactly the snapshotted value.
    event["repair_deadline"] = extension["deadline_before"]
    if (event["status"] == "OPEN"
            and deadlines.is_overdue(event["repair_deadline"], clock)):
        event["status"] = "REPAIR_OVERDUE"
    db.commit(event, event_snap)
    db.commit(extension, snap)
    system = db.require("systems", event["system_id"])
    posture.recompute_store_by_id(system["store_id"])
    return response.ok(extension)
