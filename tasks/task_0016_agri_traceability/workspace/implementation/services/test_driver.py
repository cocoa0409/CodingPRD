"""Test-only driving utilities."""

from clock import clock
from common import get_json_body, parse_iso_datetime, require_field
from db import db
from errors import ERR_VALIDATION, raise_error
from services.audit import record_audit


def advance_clock():
    body = get_json_body()
    to_iso = require_field(body, "to", str)
    target = parse_iso_datetime(to_iso, "to")
    clock.set_to(target.timestamp())
    return {"now": clock.now_iso()}


def emit_event():
    body = get_json_body()
    event_type = require_field(body, "event_type", str)
    payload = body.get("payload") or {}
    if not isinstance(payload, dict):
        raise_error(ERR_VALIDATION, "payload must be object")

    handled = {"event_type": event_type, "actions": []}

    if event_type == "REGULATORY_PROHIBITION_NOTICE":
        # Mark a registry record prohibited; cascade no automatic recall by default.
        regno = payload.get("registration_no")
        prohibited_since = payload.get("prohibited_since")
        if regno and prohibited_since:
            reg = db.pesticide_registry.get(regno)
            if reg is not None:
                reg["prohibited"] = True
                reg["prohibited_since"] = prohibited_since
                handled["actions"].append({"prohibited_registry": regno})
                record_audit(
                    "PesticideRegistry", reg["id"], "UPDATE", "prohibited",
                    before_state="active",
                    change_summary={"event": event_type},
                )
    elif event_type == "DISTRIBUTOR_NOTIFICATION":
        # Record an external distributor notification
        db.notifications.append({"event_type": event_type, "payload": payload})
        handled["actions"].append({"notification": "queued"})
    elif event_type == "RETAIL_SALE":
        handled["actions"].append({"observed": True})
    else:
        handled["actions"].append({"observed": True})

    return handled
