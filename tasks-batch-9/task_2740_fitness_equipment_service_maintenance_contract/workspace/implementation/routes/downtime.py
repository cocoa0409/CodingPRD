"""Downtime events: reads and the goodwill / data-quality waiver."""
from flask import Blueprint

import db
import middleware
import response
from errors import ApiError
from services import credit, domain, validate

bp = Blueprint("downtime", __name__)


@bp.get("/fleetcare/downtime-events")
def list_events():
    middleware.auth(*middleware.ALL_ROLES)
    return response.listing(db.downtime_events, {
        "contract_id": response.arg("contract_id"),
        "equipment_id": response.arg("equipment_id"),
        "service_call_id": response.arg("service_call_id"),
        "status": response.arg("status"),
        "period_key": response.arg("period_key"),
    })


@bp.get("/fleetcare/downtime-events/<event_id>")
def read_event(event_id):
    ctx = middleware.auth(*middleware.ALL_ROLES)
    event = domain.need_downtime_event(event_id)
    middleware.require_club_scope(ctx, domain.club_id_of_contract(event["contract_id"]))
    return response.object_response(event)


@bp.post("/fleetcare/downtime-events/<event_id>/waive")
def waive_event(event_id):
    middleware.auth(middleware.CONTRACT_ADMIN)
    event = domain.need_downtime_event(event_id)
    body = middleware.body()
    reason = validate.string(body, "waive_reason", min_len=1)
    # WAIVED is the one terminal status: it cannot be waived a second time.
    if event["status"] == "WAIVED":
        raise ApiError("ERR_DOWNTIME_INVALID_STATE")

    credit.waive_event(event, reason)
    return response.object_response(event)
