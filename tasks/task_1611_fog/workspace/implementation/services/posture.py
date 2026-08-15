"""Compliance posture reconciliation and cascades (PRD §2.7)."""
from db import STORE
from services.calculations import compute_posture


def cascade_suspend_variances(est_id, current):
    """Entering SUSPENDED force-denies every open variance of the establishment."""
    for var in STORE["variances"].values():
        if var["establishment_id"] == est_id and var["status"] in ("UNDER_REVIEW", "INFO_REQUESTED"):
            var["status"] = "DENIED"
            var["decided_at"] = current
            var["approved_by_user_id"] = None
            var["updated_at"] = current
            var["version"] += 1


def touch_establishment(est, current, bump):
    """Recompute compliance_status from underlying facts. If the posture
    changed (or `bump` is set because the caller mutated a stored field in the
    same operation), advance version once and refresh updated_at. Cascade
    variance denials when newly entering SUSPENDED."""
    old = est["compliance_status"]
    new = compute_posture(est, current)
    status_changed = new != old
    est["compliance_status"] = new
    if status_changed or bump:
        est["version"] += 1
        est["updated_at"] = current
    if status_changed and new == "SUSPENDED":
        cascade_suspend_variances(est["id"], current)


def suspend_hauler(hauler, current):
    """PERMITTED -> SUSPENDED; cascade-reject every still-SUBMITTED manifest
    naming this hauler with reject_reason HAULER_SUSPENDED."""
    hauler["status"] = "SUSPENDED"
    hauler["updated_at"] = current
    hauler["version"] += 1
    for m in STORE["manifests"].values():
        if m["hauler_id"] == hauler["id"] and m["status"] == "SUBMITTED":
            m["status"] = "REJECTED"
            m["reject_reason"] = "HAULER_SUSPENDED"
            m["updated_at"] = current
            m["version"] += 1
