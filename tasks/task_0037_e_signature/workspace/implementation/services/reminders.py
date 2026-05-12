"""ReminderRule + ReminderEvent + sweep logic per PRD §3.8."""

import math

from db import DB, new_id
from clock import now
from errors import (
    APIError, validation_failed, version_conflict, invalid_state, not_found,
    ERR_DUPLICATE_REMINDER,
)
from services.audit import append_audit


VALID_CHANNELS = {"SMS", "EMAIL", "IM"}


def _validate_rule_payload(payload: dict, *, partial: bool = False):
    if not isinstance(payload, dict):
        raise validation_failed("Body must be a JSON object")
    if "interval_hours" in payload:
        ih = payload["interval_hours"]
        if not isinstance(ih, int) or isinstance(ih, bool) or ih < 1 or ih > 168:
            raise validation_failed("interval_hours must be 1..168")
    elif not partial:
        raise validation_failed("interval_hours required")
    if "channels" in payload:
        ch = payload["channels"]
        if not isinstance(ch, list) or not ch:
            raise validation_failed("channels must be a non-empty array")
        if len(set(ch)) != len(ch):
            raise validation_failed("channels must be unique")
        for c in ch:
            if c not in VALID_CHANNELS:
                raise validation_failed(f"invalid channel: {c}")
    elif not partial:
        raise validation_failed("channels required")
    if "escalation_after_misses" in payload:
        e = payload["escalation_after_misses"]
        if not isinstance(e, int) or isinstance(e, bool) or e < 0 or e > 10:
            raise validation_failed("escalation_after_misses must be 0..10")
    elif not partial:
        raise validation_failed("escalation_after_misses required")


def create_reminder_rule(contract_id: str, payload: dict) -> dict:
    from services.contracts import get_contract
    c = get_contract(contract_id)
    _validate_rule_payload(payload, partial=False)
    n = now()
    rid = new_id()
    enabled = payload.get("enabled")
    if enabled is None:
        enabled = True
    r = {
        "id": rid,
        "contract_id": contract_id,
        "interval_hours": payload["interval_hours"],
        "channels": list(payload["channels"]),
        "escalation_after_misses": payload["escalation_after_misses"],
        "enabled": bool(enabled),
        "last_fired_at": None,
        "misses_count": 0,
        "version": 1,
        "created_at": n,
        "updated_at": n,
    }
    DB.reminder_rules[rid] = r
    return r


def get_reminder_rule(rid: str) -> dict:
    r = DB.reminder_rules.get(rid)
    if not r:
        raise not_found("ReminderRule not found")
    return r


def patch_reminder_rule(rid: str, payload: dict) -> dict:
    r = get_reminder_rule(rid)
    if not isinstance(payload, dict):
        raise validation_failed("Body must be a JSON object")
    if "version" in payload and payload["version"] is not None:
        if payload["version"] != r["version"]:
            raise version_conflict("Version mismatch")
    _validate_rule_payload(payload, partial=True)
    for k in ("interval_hours", "channels", "escalation_after_misses", "enabled"):
        if k in payload:
            r[k] = payload[k]
    r["version"] += 1
    r["updated_at"] = now()
    return r


def fire_reminder(rid: str, payload: dict, *, actor_user_id: str, actor_role: str) -> dict:
    """Fire a single reminder event for the rule with the given idempotency_key.

    Note: this endpoint expects the caller to provide the idempotency_key and
    bumps misses_count + last_fired_at unconditionally, per scaffold semantics.
    """
    r = get_reminder_rule(rid)
    if not isinstance(payload, dict):
        raise validation_failed("Body must be a JSON object")
    idem = payload.get("idempotency_key")
    if not isinstance(idem, str) or not idem:
        raise validation_failed("idempotency_key required")
    key = (rid, idem)
    if key in DB.reminder_idem:
        raise APIError(ERR_DUPLICATE_REMINDER, "Duplicate reminder for idempotency_key", 409)
    n = now()
    new_misses = r["misses_count"] + 1
    escalated = new_misses > r["escalation_after_misses"]
    channels_used = list(r["channels"])
    if escalated and "INITIATOR_IM" not in channels_used:
        channels_used = channels_used + ["INITIATOR_IM"]
    eid = new_id()
    e = {
        "id": eid,
        "reminder_rule_id": rid,
        "contract_id": r["contract_id"],
        "fired_at": n,
        "channels_used": channels_used,
        "escalated": escalated,
        "idempotency_key": idem,
        "created_at": n,
    }
    DB.reminder_events[eid] = e
    DB.reminder_idem[key] = eid
    r["misses_count"] = new_misses
    r["last_fired_at"] = n
    r["version"] += 1
    r["updated_at"] = n
    append_audit(
        contract_id=r["contract_id"],
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action="REMINDER_FIRED",
        payload={
            "reminder_rule_id": rid,
            "idempotency_key": idem,
            "escalated": escalated,
        },
    )
    return e


def list_reminder_events(contract_id: str, limit: int = 10, offset: int = 0):
    from services.contracts import get_contract
    get_contract(contract_id)
    rows = [e for e in DB.reminder_events.values() if e["contract_id"] == contract_id]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    return rows[offset:offset + limit], total
