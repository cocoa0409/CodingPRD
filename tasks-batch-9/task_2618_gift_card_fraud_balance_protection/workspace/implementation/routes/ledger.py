"""Ledger events and reversal (PRD 3.4)."""
from flask import Blueprint

import db as dbm
import response
import validate
from db import db
from errors import fail
from routes.common import (READ_ROLES, authenticate, filter_by, listing_response,
                           require_event)
from services import cards as card_svc
from services.cards import EVENT_TYPES

bp = Blueprint("ledger", __name__)


@bp.get("/ledger-events")
def list_events():
    authenticate(READ_ROLES)
    card_id = validate.query_str("card_id")
    merchant_store_id = validate.query_str("merchant_store_id")
    reverses_event_id = validate.query_str("reverses_event_id")
    event_type = validate.query_enum("type", EVENT_TYPES)
    rows = list(db.events.values())
    rows = filter_by(rows, "card_id", card_id)
    rows = filter_by(rows, "merchant_store_id", merchant_store_id)
    rows = filter_by(rows, "reverses_event_id", reverses_event_id)
    rows = filter_by(rows, "type", event_type)
    return listing_response(rows, order_keys=["occurred_at"])


@bp.get("/ledger-events/<event_id>")
def get_event(event_id):
    authenticate(READ_ROLES)
    return response.ok(require_event(event_id))


@bp.post("/ledger-events/<event_id>/reverse")
def reverse_event(event_id):
    caller = authenticate(["RiskManager"])
    body = validate.body()
    reason = validate.string(body, "reversal_reason", min_len=None)
    original = require_event(event_id)

    if original["type"] != "REDEMPTION":
        fail("ERR_LEDGER_EVENT_ALREADY_REVERSED")
    if original["id"] in card_svc.reversed_event_ids():
        fail("ERR_LEDGER_EVENT_ALREADY_REVERSED")

    card = db.cards.get(original["card_id"])
    # Deliberately NOT gated by the frozen-card guard.
    reversal = card_svc.append_event(
        card, "REDEMPTION_REVERSAL", original["amount_cents"], caller.user_id,
        reverses_event_id=original["id"], memo=reason,
    )
    if card is not None:
        card_svc.recompute(card)
        card_svc.apply_funding_edges(card)
        dbm.touch(card)
    return response.created(reversal)
