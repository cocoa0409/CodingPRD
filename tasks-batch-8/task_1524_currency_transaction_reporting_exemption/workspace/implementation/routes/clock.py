"""Logical clock endpoints."""
from flask import Blueprint, g

from db import now_iso, store
from errors import bad_request
from middleware import authenticate, body
from db import parse_dt
from response import ok
from serializers import serialize_exemption
from services.audit import add_fx, main_event, system_event
from services.domain import sweep_review_due

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(["SystemAdmin"])
    b = body()
    raw = b.get("to_iso8601")
    dt = parse_dt(raw)
    if dt is None:
        raise bad_request("to_iso8601 is required and must be an ISO 8601 datetime")
    store.clock = dt
    # Synchronous sweep; cascade SYSTEM_AUTO events land first, then one
    # SYSTEM_SWEEP event per swept designation, then this call's own event.
    swept = sweep_review_due()
    for designation, before in swept:
        system_event(
            "SYSTEM_SWEEP",
            "ExemptionDesignation",
            designation["id"],
            before,
            serialize_exemption(designation),
        )
        add_fx({
            "type": "exemption_review_due",
            "exemption_id": designation["id"],
        })
    main_event(
        "POST /_clock/set_current_utc",
        "LogicalClock",
        "logical-clock",
        None,
        {"current_utc": now_iso()},
    )
    return ok({"current_utc": now_iso()})
