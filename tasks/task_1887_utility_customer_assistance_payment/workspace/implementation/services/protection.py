"""Protection gate (calc: protection_gate) and shutoff-order sync (PRD §2.10).

Medical outranks weather. Persisted protection_status is recomputed on the
daily sweep and on certificate create/renew/revoke. Weather observations only
exist within a sweep; outside it, the weather trigger is the winter season.
"""

import db
from db import CLOCK
from services.common import covering_certificate, open_order

COLD_THRESHOLD_F = 32
HEAT_THRESHOLD_F = 95


def is_winter(d):
    """Winter season: [Nov 1, Apr 1) UTC."""
    return d.month >= 11 or d.month <= 3


def evaluate_protection(account, observed_low_f=None, observed_heat_index_f=None):
    if covering_certificate(account["id"]) is not None:
        return "MEDICAL_MORATORIUM"
    today = CLOCK.date()
    if is_winter(today):
        return "WEATHER_MORATORIUM"
    if observed_low_f is not None and observed_low_f <= COLD_THRESHOLD_F:
        return "WEATHER_MORATORIUM"
    if observed_heat_index_f is not None and observed_heat_index_f >= HEAT_THRESHOLD_F:
        return "WEATHER_MORATORIUM"
    return "UNPROTECTED"


def recompute(account, observed_low_f=None, observed_heat_index_f=None, tally=None):
    """Recompute protection_status; sync an open order on any change.
    Returns True when the account's protection_status changed."""
    old = account["protection_status"]
    new = evaluate_protection(account, observed_low_f, observed_heat_index_f)
    if new == old:
        return False
    account["protection_status"] = new
    order = open_order(account["id"])
    if order is not None:
        if new == "UNPROTECTED" and order["status"] == "BLOCKED":
            order["status"] = "SCHEDULED"
            order["blocked_reason"] = None
            db.touch(order)
            if tally is not None:
                tally["orders_unblocked"] += 1
        elif new in ("WEATHER_MORATORIUM", "MEDICAL_MORATORIUM"):
            reason = "WEATHER" if new == "WEATHER_MORATORIUM" else "MEDICAL"
            if order["status"] == "SCHEDULED":
                order["status"] = "BLOCKED"
                order["blocked_reason"] = reason
                db.touch(order)
                if tally is not None:
                    tally["orders_blocked"] += 1
            elif order["status"] == "BLOCKED" and order["blocked_reason"] != reason:
                order["blocked_reason"] = reason
                db.touch(order)
    return True
