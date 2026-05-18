"""Virtual clock endpoints (PRD §2.9)."""
from __future__ import annotations

from flask import Blueprint

from config import (
    ACCOUNT_ACTIVE,
    PAYMENT_CONFIRMED,
    PAYMENT_SCHEDULED,
    ROLE_IRSADJUDICATOR,
    ROLE_TAXPAYER,
)
from db import store
from errors import err_invalid_input
from middleware import require_auth
from response import success
from services import engine
from utils import iso_now, parse_iso

from routes._helpers import get_json


bp = Blueprint("clock", __name__)


@bp.get("/_clock")
@require_auth([ROLE_TAXPAYER, ROLE_IRSADJUDICATOR])
def read_clock():
    return success({"now": iso_now(store.clock_now())}, 200)


@bp.post("/_clock/advance")
@require_auth([ROLE_TAXPAYER, ROLE_IRSADJUDICATOR])
def advance_clock():
    body = get_json()
    target_raw = body.get("to_iso_timestamp")
    if not isinstance(target_raw, str) or not target_raw.strip():
        raise err_invalid_input("to_iso_timestamp must be an ISO 8601 timestamp string")
    try:
        target = parse_iso(target_raw)
    except Exception:
        raise err_invalid_input("to_iso_timestamp must be a valid ISO 8601 timestamp")

    transitions = []
    with store.lock:
        new_now = store.clock.advance_to(target)
        # Run deferred transitions: SCHEDULED → CONFIRMED for every
        # EstimatedTaxPayment whose pay-date is at or before the new clock,
        # whose owning Taxpayer is ACTIVE.
        # Iterate in a stable order (created_at).
        payments = sorted(
            store.estimated_payments.values(), key=lambda x: x["created_at"]
        )
        for p in payments:
            if p["status"] != PAYMENT_SCHEDULED:
                continue
            from utils import parse_date_to_midnight_utc

            pay_dt = parse_date_to_midnight_utc(p["scheduled_pay_date"])
            if new_now < pay_dt:
                continue
            tp = store.taxpayers.get(p["taxpayer_id"])
            if tp is None or tp["account_status"] != ACCOUNT_ACTIVE:
                continue
            p["status"] = PAYMENT_CONFIRMED
            p["confirmed_at"] = iso_now(new_now)
            engine.stamp_update(p)
            transitions.append(
                {
                    "entity": "EstimatedTaxPayment",
                    "id": p["id"],
                    "from": PAYMENT_SCHEDULED,
                    "to": PAYMENT_CONFIRMED,
                }
            )

    return success(
        {
            "now": iso_now(store.clock_now()),
            "advanced_transitions": transitions,
        },
        200,
    )
