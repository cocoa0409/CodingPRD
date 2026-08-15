"""Carrier eligibility posture machine and the safety deactivation cascade
(PRD 3.2; calculation carrier_eligibility_posture).

Posture is a derived, parallel dimension on Carrier, orthogonal to lifecycle
status. Boundaries are inclusive-lower: iss 75 => INELIGIBLE, 74 => CONDITIONAL,
50 => CONDITIONAL, 49 => ELIGIBLE.
"""
import db
from db import store
from util import fmt_ts

ISS_CONDITIONAL_FLOOR = 50
ISS_INELIGIBLE_FLOOR = 75


def latest_snapshot(carrier_id):
    """Latest = max effective_date; ties broken toward most recently created."""
    snaps = [s for s in store.snapshots.values() if s["carrier_id"] == carrier_id]
    if not snaps:
        return None
    return max(snaps, key=lambda s: (s["_effective"], s["_seq"]))


def in_force_override(carrier_id):
    """An override is in force when ACTIVE and today in [start_date, end_date)."""
    t = db.today()
    for o in store.overrides.values():
        if (
            o["carrier_id"] == carrier_id
            and o["status"] == "ACTIVE"
            and o["_start"] <= t < o["_end"]
        ):
            return o
    return None


def compute_posture(carrier):
    if in_force_override(carrier["id"]) is not None:
        return "ELIGIBLE"
    s = latest_snapshot(carrier["id"])
    if s is None:
        return "NOT_EVALUATED"
    if s["safety_rating"] == "UNSATISFACTORY" or s["iss_score"] >= ISS_INELIGIBLE_FLOOR:
        return "INELIGIBLE"
    if s["safety_rating"] == "CONDITIONAL" or s["iss_score"] >= ISS_CONDITIONAL_FLOOR:
        return "CONDITIONAL"
    return "ELIGIBLE"


def recompute_posture(carrier):
    """Recompute eligibility_status; fire the safety cascade on entry into
    INELIGIBLE from ELIGIBLE/CONDITIONAL (NOT_EVALUATED->INELIGIBLE has no
    cascade per the state machine)."""
    old = carrier["eligibility_status"]
    new = compute_posture(carrier)
    if new == old:
        return
    carrier["eligibility_status"] = new
    carrier["updated_at"] = fmt_ts(db.now())
    if new == "INELIGIBLE" and old in ("ELIGIBLE", "CONDITIONAL"):
        safety_cascade(carrier)


def safety_cascade(carrier):
    """Every ACTIVE credential of the carrier -> SUSPENDED (SAFETY_INELIGIBLE);
    each such suspension pauses ITS vehicle's ACTIVE subscription
    (paused_at := today). Increments Carrier.version by 1. Lifecycle status is
    never touched by posture."""
    today_s = db.today().isoformat()
    for cred in store.credentials.values():
        if cred["carrier_id"] == carrier["id"] and cred["status"] == "ACTIVE":
            cred["status"] = "SUSPENDED"
            cred["status_reason"] = "SAFETY_INELIGIBLE"
            db.bump(cred)
            for sub in store.subscriptions.values():
                if sub["vehicle_id"] == cred["vehicle_id"] and sub["status"] == "ACTIVE":
                    sub["status"] = "PAUSED"
                    sub["paused_at"] = today_s
                    db.bump(sub)
    carrier["version"] += 1
    carrier["updated_at"] = fmt_ts(db.now())
