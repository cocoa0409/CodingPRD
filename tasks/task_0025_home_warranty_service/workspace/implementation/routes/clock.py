"""Test-driving endpoints: /_clock/set and /_clock/tick (PRD §3.9)."""
from __future__ import annotations

import math
from datetime import timedelta
from typing import Dict, Any, List

from flask import Blueprint

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import require_auth, get_json_body
from response import ok_object
from services.validation import require_fields


bp = Blueprint("clock", __name__)


@bp.post("/_clock/set")
def set_clock():
    require_auth(["PlatformAdmin"])()
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    iso = body["to_iso8601"]
    try:
        dt = db.parse_iso_dt(iso)
    except (ValueError, TypeError, AttributeError):
        raise APIError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be ISO 8601")
    if dt is None:
        raise APIError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be ISO 8601")
    # Normalize to canonical ISO form.
    canonical = db.iso_format(dt)
    state = db.set_current_utc(canonical)
    return ok_object(state, 200)


@bp.post("/_clock/tick")
def tick_clock():
    """Scan ACTIVE/EXPIRING_SOON contracts and fire eligible auto-transitions.

    Order per contract:
      1. If ACTIVE and clock_now >= coverage_end_utc, fire ACTIVE -> EXPIRED.
         (PRD §3.8: 'When the clock advances past coverage_end_utc ... any
         contract in ACTIVE or EXPIRING_SOON whose coverage_end_utc has been
         reached is transitioned to EXPIRED'.)
      2. If ACTIVE and coverage_end_utc - 30d <= clock_now < coverage_end_utc,
         fire ACTIVE -> EXPIRING_SOON. Guarded by renewal_reminder_sent_at IS NULL.
      3. If EXPIRING_SOON and clock_now >= coverage_end_utc, fire -> EXPIRED.

    Each fired transition bumps the contract's version. ACTIVE -> EXPIRING_SOON
    additionally writes a RenewalReminder row.
    """
    require_auth(["PlatformAdmin"])()

    now_iso = db.get_current_utc()
    now_dt = db.parse_iso_dt(now_iso)
    assert now_dt is not None

    transitions_fired = 0
    reminders_emitted = 0

    # Snapshot the iteration set — mutations happen in place.
    contracts = [
        c for c in db.contracts.values() if c["status"] in {"ACTIVE", "EXPIRING_SOON"}
    ]
    # Deterministic order: by created_at.
    contracts.sort(key=lambda c: c["created_at"])

    for contract in contracts:
        end_iso = contract.get("coverage_end_utc")
        if not end_iso:
            continue
        end_dt = db.parse_iso_dt(end_iso)
        if end_dt is None:
            continue
        status = contract["status"]

        # Check for EXPIRED first — if past coverage_end_utc, jump straight to EXPIRED.
        if now_dt >= end_dt:
            if status == "ACTIVE":
                # Also fire the missed ACTIVE -> EXPIRING_SOON reminder if not yet
                # emitted? PRD §3.8 says the scan fires the transitions the contract
                # is now eligible for. If the contract was never moved to
                # EXPIRING_SOON before passing coverage_end_utc, the reminder is
                # bypassed — we go straight to EXPIRED. (renewal_reminder_sent_at
                # stays null.) This is consistent with the scaffold transitions:
                # ACTIVE -> EXPIRED is a direct transition under {ACTIVE,EXPIRING_SOON}
                # when clock_now >= coverage_end_utc.
                contract["status"] = "EXPIRED"
                db.bump(contract)
                transitions_fired += 1
                continue
            elif status == "EXPIRING_SOON":
                contract["status"] = "EXPIRED"
                db.bump(contract)
                transitions_fired += 1
                continue

        # Not yet expired. Try the ACTIVE -> EXPIRING_SOON transition if eligible.
        if status == "ACTIVE":
            reminder_threshold = end_dt - timedelta(days=30)
            if (
                now_dt >= reminder_threshold
                and now_dt < end_dt
                and contract.get("renewal_reminder_sent_at") is None
            ):
                # Fire reminder + state transition.
                contract["renewal_reminder_sent_at"] = now_iso
                contract["status"] = "EXPIRING_SOON"
                # Compute days_to_expiry = floor((coverage_end - now)/86400).
                delta_seconds = (end_dt - now_dt).total_seconds()
                days_to_expiry = int(math.floor(delta_seconds / 86400.0))
                # Write a RenewalReminder row.
                reminder: Dict[str, Any] = {
                    "contract_id": contract["id"],
                    "sent_utc": now_iso,
                    "days_to_expiry": days_to_expiry,
                }
                db.stamp_immutable(reminder)
                db.renewal_reminders[reminder["id"]] = reminder
                reminders_emitted += 1
                db.bump(contract)
                transitions_fired += 1

    return ok_object(
        {
            "transitions_fired": transitions_fired,
            "reminders_emitted": reminders_emitted,
        },
        200,
    )
