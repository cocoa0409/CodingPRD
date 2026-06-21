"""Cross-aggregate business logic: pool-ledger recompute, supervision posture,
authorization status flips, and cascade helpers (PRD §2.7, §2.9, §3.4-§3.8).
"""
import calculations as calc
from db import db, touch

LINES = ("direct", "supervision", "parent_training")
SERVICE_LINE_TO_KEY = {
    "DIRECT_THERAPY": "direct",
    "SUPERVISION": "supervision",
    "PARENT_TRAINING": "parent_training",
}


def sessions_for_authorization(auth_id):
    return [s for s in db.therapy_sessions.values() if s["authorization_id"] == auth_id]


def _recompute_pools(auth):
    """Recompute reserved/delivered accumulators per service line and the
    direct remaining figure from the live session set (SCAFFOLD
    authorization_pool_ledger).

    SCHEDULED sessions contribute their scheduled_units to reserved; DELIVERED
    sessions contribute their delivered_units to delivered; NO_SHOW/CANCELLED
    contribute to neither.
    """
    reserved = {k: 0 for k in LINES}
    delivered = {k: 0 for k in LINES}
    for s in sessions_for_authorization(auth["id"]):
        key = SERVICE_LINE_TO_KEY[s["service_line"]]
        if s["status"] == "SCHEDULED":
            reserved[key] += s["scheduled_units"]
        elif s["status"] == "DELIVERED":
            delivered[key] += s["delivered_units"]
    for k in LINES:
        auth[f"reserved_{k}_units"] = reserved[k]
        auth[f"delivered_{k}_units"] = delivered[k]
    auth["remaining_direct_units"] = (
        auth["authorized_direct_units"]
        - auth["reserved_direct_units"]
        - auth["delivered_direct_units"]
    )


def _recompute_supervision_status(auth):
    """Recompute supervision posture against the payer ratio (PRD §3.8)."""
    payer = db.payers.get(auth["payer_id"])
    ratio = payer["supervision_ratio_pct"] if payer else 0
    auth["supervision_status"] = calc.supervision_status(
        auth["delivered_direct_units"],
        auth["delivered_supervision_units"],
        ratio,
    )


def _apply_status_flip(auth):
    """Flip ACTIVE<->EXHAUSTED based on remaining_direct_units (PRD §3.4).

    Only ACTIVE and EXHAUSTED participate; terminal EXPIRED/RENEWED are left
    untouched. Returns True if the status field changed.
    """
    if auth["status"] not in ("ACTIVE", "EXHAUSTED"):
        return False
    if auth["remaining_direct_units"] <= 0:
        target = "EXHAUSTED"
    else:
        target = "ACTIVE"
    if auth["status"] != target:
        auth["status"] = target
        return True
    return False


def recompute_authorization(auth):
    """Full atomic recompute after any session state change against this auth:
    pools -> remaining -> supervision -> status flip. This is itself a mutation
    of the authorization, so it bumps updated_at and version (PRD §2.9).
    """
    _recompute_pools(auth)
    _recompute_supervision_status(auth)
    _apply_status_flip(auth)
    touch(auth)
