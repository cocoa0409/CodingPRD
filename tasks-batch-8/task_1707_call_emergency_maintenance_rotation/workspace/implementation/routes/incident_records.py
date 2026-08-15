"""IncidentRecord endpoints."""

from datetime import timedelta

from flask import Blueprint, request

from db import store, clock
from errors import (
    ApiError,
    ERR_CALL_TICKET_NOT_FOUND,
    ERR_INCIDENT_RECORD_NOT_FOUND,
    ERR_INCIDENT_RECORD_INVALID_STATE,
    ERR_INCIDENT_RECORD_EXISTS,
    ERR_NOT_ASSIGNED_TECHNICIAN,
    ERR_CALL_TICKET_INVALID_STATE,
    ERR_INSURANCE_NOTIFICATION_REQUIRED,
    ERR_INVALID_REQUEST,
)
from helpers import (
    body,
    req_string,
    req_int,
    new_id,
    serialize_incident_record,
    touch,
    pagination_params,
)
from middleware import get_actor, require_role, require_supervisor_capable
from response import success_object, success_list
from services.calculations import (
    INSURANCE_NOTIFY_THRESHOLD_CENTS,
    INSURANCE_NOTIFY_WINDOW_HOURS,
)

bp = Blueprint("incident_records", __name__)

READ_ROLES = {"PropertyAdmin", "Dispatcher", "OnCallTechnician", "MaintenanceSupervisor"}


@bp.route("/v1/call-tickets/<callTicketId>/incident-record", methods=["POST"])
def create_incident_record(callTicketId):
    actor = get_actor()
    require_role(actor, {"OnCallTechnician", "MaintenanceSupervisor"})
    require_supervisor_capable(actor)
    ticket = store.call_tickets.get(callTicketId)
    if ticket is None:
        raise ApiError(ERR_CALL_TICKET_NOT_FOUND, "Call ticket not found", 404)
    data = body()
    narrative = req_string(data, "narrative")
    damage = req_int(data, "estimated_damage_cents", minimum=0)
    # Ticket must be ON_SCENE or MITIGATED
    if ticket["status"] not in ("ON_SCENE", "MITIGATED"):
        raise ApiError(
            ERR_CALL_TICKET_INVALID_STATE,
            "Ticket must be ON_SCENE or MITIGATED to create an incident record",
            409,
        )
    for r in store.incident_records.values():
        if r["call_ticket_id"] == ticket["id"]:
            raise ApiError(ERR_INCIDENT_RECORD_EXISTS, "Ticket already has an incident record", 409)
    now = clock.now()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 0,
        "call_ticket_id": ticket["id"],
        "narrative": narrative,
        "estimated_damage_cents": damage,
        "status": "DRAFT",
        "created_by_technician_id": actor.user_id,
        "insurance_notified_at": None,
        "insurance_claim_number": None,
        "insurance_notification_late": None,
        "insurance_waived_reason": None,
        "return_reason": None,
        "_seq": store.next_seq(),
    }
    store.incident_records[rec["id"]] = rec
    return success_object(serialize_incident_record(rec), 201)


@bp.route("/v1/incident-records", methods=["GET"])
def list_incident_records():
    actor = get_actor()
    require_role(actor, READ_ROLES)
    limit, offset = pagination_params()
    items = list(store.incident_records.values())
    for key in ("call_ticket_id", "created_by_technician_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [r for r in items if r[key] == v]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_incident_record(r) for r in page], limit, offset, total)


def _get_record_or_404(record_id):
    rec = store.incident_records.get(record_id)
    if rec is None:
        raise ApiError(ERR_INCIDENT_RECORD_NOT_FOUND, "Incident record not found", 404)
    return rec


@bp.route("/v1/incident-records/<incidentRecordId>", methods=["GET"])
def get_incident_record(incidentRecordId):
    actor = get_actor()
    require_role(actor, READ_ROLES)
    rec = _get_record_or_404(incidentRecordId)
    return success_object(serialize_incident_record(rec))


@bp.route("/v1/incident-records/<incidentRecordId>/submit", methods=["POST"])
def submit_record(incidentRecordId):
    actor = get_actor()
    require_role(actor, {"OnCallTechnician"})
    rec = _get_record_or_404(incidentRecordId)
    if rec["status"] != "DRAFT":
        raise ApiError(ERR_INCIDENT_RECORD_INVALID_STATE, "Record is not DRAFT", 409)
    if actor.user_id != rec["created_by_technician_id"]:
        raise ApiError(ERR_NOT_ASSIGNED_TECHNICIAN, "Not the record's creator", 403)
    rec["status"] = "SUBMITTED"
    touch(rec)
    return success_object(serialize_incident_record(rec))


@bp.route("/v1/incident-records/<incidentRecordId>/begin-review", methods=["POST"])
def begin_review_record(incidentRecordId):
    actor = get_actor()
    require_role(actor, {"MaintenanceSupervisor"})
    require_supervisor_capable(actor)
    rec = _get_record_or_404(incidentRecordId)
    if rec["status"] != "SUBMITTED":
        raise ApiError(ERR_INCIDENT_RECORD_INVALID_STATE, "Record is not SUBMITTED", 409)
    rec["status"] = "UNDER_REVIEW"
    touch(rec)
    return success_object(serialize_incident_record(rec))


@bp.route("/v1/incident-records/<incidentRecordId>/return", methods=["POST"])
def return_record(incidentRecordId):
    actor = get_actor()
    require_role(actor, {"MaintenanceSupervisor"})
    require_supervisor_capable(actor)
    rec = _get_record_or_404(incidentRecordId)
    data = body()
    reason = req_string(data, "reason")
    if rec["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INCIDENT_RECORD_INVALID_STATE, "Record is not UNDER_REVIEW", 409)
    rec["status"] = "RETURNED"
    rec["return_reason"] = reason
    touch(rec)
    return success_object(serialize_incident_record(rec))


@bp.route("/v1/incident-records/<incidentRecordId>/revise", methods=["POST"])
def revise_record(incidentRecordId):
    actor = get_actor()
    require_role(actor, {"OnCallTechnician"})
    rec = _get_record_or_404(incidentRecordId)
    data = body()
    narrative = req_string(data, "narrative")
    damage = req_int(data, "estimated_damage_cents", minimum=0)
    if rec["status"] != "RETURNED":
        raise ApiError(ERR_INCIDENT_RECORD_INVALID_STATE, "Record is not RETURNED", 409)
    if actor.user_id != rec["created_by_technician_id"]:
        raise ApiError(ERR_NOT_ASSIGNED_TECHNICIAN, "Not the record's creator", 403)
    rec["narrative"] = narrative
    rec["estimated_damage_cents"] = damage
    rec["status"] = "DRAFT"
    touch(rec)
    return success_object(serialize_incident_record(rec))


@bp.route("/v1/incident-records/<incidentRecordId>/notify-insurance", methods=["POST"])
def notify_insurance(incidentRecordId):
    actor = get_actor()
    require_role(actor, {"MaintenanceSupervisor", "PropertyAdmin"})
    require_supervisor_capable(actor)
    rec = _get_record_or_404(incidentRecordId)
    data = body()
    claim_number = req_string(data, "claim_number")
    now = clock.now()
    rec["insurance_notified_at"] = now
    rec["insurance_claim_number"] = claim_number
    ticket = store.call_tickets.get(rec["call_ticket_id"])
    if ticket is not None and ticket["closed_at"] is not None:
        deadline = ticket["closed_at"] + timedelta(hours=INSURANCE_NOTIFY_WINDOW_HOURS)
        rec["insurance_notification_late"] = now > deadline
    else:
        rec["insurance_notification_late"] = False
    touch(rec)
    return success_object(serialize_incident_record(rec))


@bp.route("/v1/incident-records/<incidentRecordId>/finalize", methods=["POST"])
def finalize_record(incidentRecordId):
    actor = get_actor()
    require_role(actor, {"MaintenanceSupervisor"})
    require_supervisor_capable(actor)
    rec = _get_record_or_404(incidentRecordId)
    data = body()
    waived_reason = data.get("insurance_waived_reason")
    if waived_reason is not None and not isinstance(waived_reason, str):
        raise ApiError(ERR_INVALID_REQUEST, "insurance_waived_reason must be a string", 400)
    if rec["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INCIDENT_RECORD_INVALID_STATE, "Record is not UNDER_REVIEW", 409)
    ticket = store.call_tickets.get(rec["call_ticket_id"])
    if ticket is None or ticket["status"] != "CLOSED":
        raise ApiError(ERR_CALL_TICKET_INVALID_STATE, "Parent ticket is not CLOSED", 409)
    notified = rec["insurance_notified_at"] is not None
    if rec["estimated_damage_cents"] >= INSURANCE_NOTIFY_THRESHOLD_CENTS:
        if not notified:
            raise ApiError(
                ERR_INSURANCE_NOTIFICATION_REQUIRED,
                "Insurance notification is required at this damage level",
                409,
            )
    else:
        if not notified and not waived_reason:
            raise ApiError(
                ERR_INSURANCE_NOTIFICATION_REQUIRED,
                "Insurance notification or waiver reason is required",
                409,
            )
    if waived_reason:
        rec["insurance_waived_reason"] = waived_reason
    rec["status"] = "FINALIZED"
    touch(rec)
    return success_object(serialize_incident_record(rec))
