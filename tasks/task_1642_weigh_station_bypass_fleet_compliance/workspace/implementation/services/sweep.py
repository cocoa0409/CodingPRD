"""Clock-driven materialization sweep and the past-due invoice sweep
(PRD 2.4, 3.4, 3.8)."""
from datetime import date

import db
from db import store
from services.posture import recompute_posture


def close_subscription(sub, reason):
    """Close a SCHEDULED/ACTIVE/PAUSED subscription. A PAUSED row first accrues
    its open pause interval (today - paused_at) into paused_days_current_period.
    service_end_date pulls back to today when it still lies in the future."""
    today = db.today()
    if sub["status"] == "PAUSED" and sub["paused_at"]:
        sub["paused_days_current_period"] += (
            today - date.fromisoformat(sub["paused_at"])
        ).days
        sub["paused_at"] = None
    sub["status"] = "CLOSED"
    sub["closed_reason"] = reason
    if date.fromisoformat(sub["service_end_date"]) > today:
        sub["service_end_date"] = today.isoformat()
        sub["_end"] = today
    db.bump(sub)


def past_due_sweep(carrier_id=None):
    """ISSUED invoices whose due_date lies in the past flip to PAST_DUE and
    propagate payment_standing PAST_DUE onto the carrier's SCHEDULED/ACTIVE/
    PAUSED subscriptions. Returns the number of invoices flipped."""
    today = db.today()
    flipped = 0
    for inv in sorted(store.invoices.values(), key=lambda i: i["_seq"]):
        if carrier_id is not None and inv["carrier_id"] != carrier_id:
            continue
        if inv["status"] == "ISSUED" and date.fromisoformat(inv["due_date"]) < today:
            inv["status"] = "PAST_DUE"
            db.bump(inv)
            flipped += 1
            for sub in store.subscriptions.values():
                if (
                    sub["carrier_id"] == inv["carrier_id"]
                    and sub["status"] in ("SCHEDULED", "ACTIVE", "PAUSED")
                    and sub["payment_standing"] == "CURRENT"
                ):
                    sub["payment_standing"] = "PAST_DUE"
                    db.bump(sub)
    return flipped


def materialization_sweep():
    """Runs on every clock set, in this order of concern (PRD 2.4):
    (1) overrides APPROVED->ACTIVE / ACTIVE->EXPIRED with posture recompute;
    (2) subscriptions SCHEDULED->ACTIVE / ->CLOSED(EXPIRED);
    (3) invoices ISSUED->PAST_DUE with standing propagation."""
    today = db.today()
    tallies = {
        "overrides_activated": 0,
        "overrides_expired": 0,
        "subscriptions_activated": 0,
        "subscriptions_expired": 0,
        "invoices_marked_past_due": 0,
    }
    for o in sorted(store.overrides.values(), key=lambda x: x["_seq"]):
        if o["status"] == "APPROVED" and today >= o["_start"]:
            o["status"] = "ACTIVE"
            db.bump(o)
            tallies["overrides_activated"] += 1
            carrier = store.carriers.get(o["carrier_id"])
            if carrier is not None:
                recompute_posture(carrier)
    for o in sorted(store.overrides.values(), key=lambda x: x["_seq"]):
        if o["status"] == "ACTIVE" and today >= o["_end"]:
            o["status"] = "EXPIRED"
            db.bump(o)
            tallies["overrides_expired"] += 1
            carrier = store.carriers.get(o["carrier_id"])
            if carrier is not None:
                recompute_posture(carrier)
    for s in sorted(store.subscriptions.values(), key=lambda x: x["_seq"]):
        if s["status"] == "SCHEDULED" and today >= s["_start"]:
            s["status"] = "ACTIVE"
            db.bump(s)
            tallies["subscriptions_activated"] += 1
    for s in sorted(store.subscriptions.values(), key=lambda x: x["_seq"]):
        if s["status"] in ("SCHEDULED", "ACTIVE", "PAUSED") and today > s["_end"]:
            close_subscription(s, "EXPIRED")
            tallies["subscriptions_expired"] += 1
    tallies["invoices_marked_past_due"] = past_due_sweep()
    return tallies
