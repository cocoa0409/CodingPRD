"""GaugeTicket endpoints: record (append-only), list."""
from flask import Blueprint

from clock import CLOCK
from db import STORE, new_id
from errors import err
from middleware import require_roles, current_user
from response import success_object, success_list
from serializers import gauge_ticket_view
from services.common import get_movement_or_404
from validation import (get_body, req_enum, req_number, req_datetime,
                        sort_and_page, TICKET_TYPES)

bp = Blueprint("gauge_tickets", __name__)


@bp.post("/movements/<movementId>/gauge-tickets")
def create_gauge_ticket(movementId):
    user_id, _ = require_roles("Gauger")
    body = get_body()
    ticket_type = req_enum(body, "ticket_type", TICKET_TYPES)
    observed_volume_bbl = req_number(body, "observed_volume_bbl", ge=0)
    observed_temp_f = req_number(body, "observed_temp_f")
    observed_at = req_datetime(body, "observed_at")

    movement = get_movement_or_404(movementId)

    existing = [g for g in STORE.gauge_tickets.values()
                if g["movement_id"] == movement["id"]]
    opening = next((g for g in existing if g["ticket_type"] == "OPENING"), None)
    closing = next((g for g in existing if g["ticket_type"] == "CLOSING"), None)

    # Gauge sequencing (priority 19).
    if ticket_type == "OPENING":
        if movement["status"] not in ("ARRIVED", "IN_PROGRESS"):
            raise err("ERR_GAUGE_SEQUENCE_INVALID",
                      "An OPENING ticket requires movement status ARRIVED or IN_PROGRESS")
        if opening is not None:
            raise err("ERR_GAUGE_SEQUENCE_INVALID",
                      "At most one OPENING ticket exists per movement")
    else:  # CLOSING
        if movement["status"] != "IN_PROGRESS":
            raise err("ERR_GAUGE_SEQUENCE_INVALID",
                      "A CLOSING ticket requires movement status IN_PROGRESS")
        if opening is None:
            raise err("ERR_GAUGE_SEQUENCE_INVALID",
                      "A CLOSING ticket requires an existing OPENING")
        if closing is not None:
            raise err("ERR_GAUGE_SEQUENCE_INVALID",
                      "At most one CLOSING ticket exists per movement")

    ticket = {
        "id": new_id(),
        "movement_id": movement["id"],
        "ticket_type": ticket_type,
        "observed_volume_bbl": observed_volume_bbl,
        "observed_temp_f": observed_temp_f,
        "observed_at": observed_at,
        "recorded_by_user_id": user_id,
        "created_at": CLOCK.now(),
    }
    STORE.gauge_tickets[ticket["id"]] = ticket
    return success_object(gauge_ticket_view(ticket), status=201)


@bp.get("/movements/<movementId>/gauge-tickets")
def list_gauge_tickets(movementId):
    current_user()
    get_movement_or_404(movementId)
    rows = [g for g in STORE.gauge_tickets.values() if g["movement_id"] == movementId]
    page, total, limit, offset = sort_and_page(rows)
    return success_list([gauge_ticket_view(g) for g in page], total, limit, offset)
