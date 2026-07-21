"""Shared cascade side effects (§3.5, §3.9)."""
from store import db, touch

OPEN_DEMAND_STATES = {"ISSUED", "DISPUTED"}
LIVE_ARBITRATION_STATES = {"FILED", "AWAITING_RESPONSE", "RESPONSE_FILED"}


def withdraw_open_demands(claim_id):
    for d in db.demands.values():
        if d["claim_id"] == claim_id and d["status"] in OPEN_DEMAND_STATES:
            d["status"] = "WITHDRAWN"
            touch(d)


def withdraw_live_arbitrations(claim_id):
    for a in db.arbitrations.values():
        if a["claim_id"] == claim_id and a["status"] in LIVE_ARBITRATION_STATES:
            a["status"] = "WITHDRAWN"
            touch(a)
