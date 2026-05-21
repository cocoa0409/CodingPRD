"""Test-driving harness endpoints: /_clock/advance and /_events/emit."""
from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..clock import parse_iso, set_clock
from ..common import get_json_body, require_enum, require_fields, require_str
from ..response import respond
from ..services import sweep_offer_expiry, sweep_referral_payable
from ..store import store


admin_bp = Blueprint("admin", __name__)


SWEEP_EVENTS = {"OFFER_EXPIRY_SWEEP", "REFERRAL_PAYABLE_SWEEP"}


@admin_bp.post("/_clock/advance")
@require_auth("PlatformAdmin")
def advance_clock():
    body = get_json_body()
    require_fields(body, "to")
    to_raw = require_str(body["to"], "to")
    try:
        to_dt = parse_iso(to_raw)
    except ValueError as exc:
        from ..errors import ApiError
        raise ApiError("ERR_VALIDATION", str(exc))
    set_clock(to_dt)
    # Drive eligible auto-transitions in the order the PRD describes.
    with store.lock:
        sweep_offer_expiry()
        sweep_referral_payable()
    return respond({}, 200)


@admin_bp.post("/_events/emit")
@require_auth("PlatformAdmin")
def emit_event():
    body = get_json_body()
    require_fields(body, "event_type")
    event_type = require_enum(body["event_type"], "event_type", SWEEP_EVENTS)
    with store.lock:
        if event_type == "OFFER_EXPIRY_SWEEP":
            sweep_offer_expiry()
        elif event_type == "REFERRAL_PAYABLE_SWEEP":
            sweep_referral_payable()
    return respond({}, 200)
