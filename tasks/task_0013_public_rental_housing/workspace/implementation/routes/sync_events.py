"""SyncEvent emission + listing."""
from flask import Blueprint, request

from common import (
    get_json_body,
    get_program_or_404,
    paginate,
    require_field,
)
from db import db
from errors import api_error
from middleware import require_roles
from response import success
from services.sync import emit_sync_event

bp = Blueprint("sync_events", __name__)


VALID_EVENT_TYPES = {
    "CIVIL_AFFAIRS_HOUSEHOLD",
    "PUBLIC_SECURITY_IDENTITY",
    "TAX_INCOME_ASSETS",
    "SOCIAL_SECURITY_INCOME",
    "PAYMENT_DEPOSIT",
    "PAYMENT_RENT",
    "AUDIT_ELIGIBILITY_CHANGE",
    "AUDIT_ALLOCATION_DECISION",
}
VALID_SUBJECT_TYPES = {"APPLICATION", "ALLOCATION", "CONTRACT", "RENT_REDUCTION"}


@bp.post("/housing-programs/<program_id>/sync-events")
def create_sync_event(program_id):
    require_roles("HousingOfficer", "IntegrationGateway")
    program = get_program_or_404(program_id)
    body = get_json_body()

    event_type = require_field(body, "event_type")
    subject_type = require_field(body, "subject_type")
    subject_id = require_field(body, "subject_id")
    payload = body.get("payload", {})
    if event_type not in VALID_EVENT_TYPES:
        raise api_error("ERR_INVALID_REQUEST", f"Unknown event_type: {event_type}")
    if subject_type not in VALID_SUBJECT_TYPES:
        raise api_error("ERR_INVALID_REQUEST", f"Unknown subject_type: {subject_type}")
    if not isinstance(payload, dict):
        raise api_error("ERR_INVALID_REQUEST", "payload must be an object")

    with db.lock:
        event = emit_sync_event(
            program_id=program_id,
            event_type=event_type,
            subject_type=subject_type,
            subject_id=str(subject_id),
            payload=payload,
            current_period_index=int(program["current_period_index"]),
        )
    return success(event, status=201)


@bp.get("/housing-programs/<program_id>/sync-events")
def list_sync_events(program_id):
    require_roles("HousingDirector", "HousingOfficer", "Applicant", "Citizen",
                  "IntegrationGateway")
    get_program_or_404(program_id)

    event_type = request.args.get("event_type")
    subject_type = request.args.get("subject_type")
    subject_id = request.args.get("subject_id")

    items = []
    for e in db.sync_events.values():
        if e.get("housing_program_id") != program_id:
            continue
        if event_type and e.get("event_type") != event_type:
            continue
        if subject_type and e.get("subject_type") != subject_type:
            continue
        if subject_id and e.get("subject_id") != subject_id:
            continue
        items.append(e)
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)
