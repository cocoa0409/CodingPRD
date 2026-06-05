"""Cross-entity cascades and shared side-effects (PRD §2.6, §3.1, §3.3, §3.4)."""
from __future__ import annotations

import db


def flag_fan_cascade(fan: dict) -> None:
    """Transition a fan to FLAGGED and revoke their live queue holds.

    PRD §3.1: flagging revokes every one of that fan's queue entries in
    WAITING or OFFERED. Revoking an OFFERED entry releases its reserved seats
    (reserved_count -= requested_qty, tier.version++); revoking a WAITING entry
    releases nothing.
    """
    fan["verification_status"] = "FLAGGED"
    db.bump(fan)

    for qe in db.queue_entries.values():
        if qe.get("fan_id") != fan["id"]:
            continue
        if qe["status"] == "WAITING":
            qe["status"] = "REVOKED"
            db.bump(qe)
        elif qe["status"] == "OFFERED":
            qe["status"] = "REVOKED"
            db.bump(qe)
            tier = db.price_tiers.get(qe.get("tier_id"))
            if tier is not None:
                tier["reserved_count"] -= qe["requested_qty"]
                db.bump(tier)


def event_sold_out_cascade(event: dict) -> None:
    """Event -> SOLD_OUT: revoke all WAITING QueueEntries for the event.

    PRD §3.4: when tickets_sold_count == venue_capacity after a PAID order,
    the event transitions from PRESALE/GENERAL to SOLD_OUT, which in turn
    revokes every remaining WAITING queue entry for the event (releases
    nothing — WAITING entries hold no reserved seats).
    """
    event["sales_status"] = "SOLD_OUT"
    db.bump(event)
    for qe in db.queue_entries.values():
        if qe.get("event_id") == event["id"] and qe["status"] == "WAITING":
            qe["status"] = "REVOKED"
            db.bump(qe)
