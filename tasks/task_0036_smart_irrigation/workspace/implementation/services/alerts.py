"""Alert helpers: creation, severity, reopen detection."""

from datetime import timedelta

from clock import CLOCK
from db import DB, new_id
from services.common import bump_version, stamp_create, to_aware_utc
from services.calculations import compute_severity


def emit_alert(rule_code, subject_type, subject_id, tenant_id):
    """Emit an alert with the provisional severity variant.

    Reopen rule: if there is a RESOLVED alert with the same (rule_code, subject_id) whose
    updated_at is within 24h, transition that alert from RESOLVED -> REOPENED instead of
    creating a new alert.
    """
    now = CLOCK.now()
    cutoff = to_aware_utc(now) - timedelta(hours=24)
    for existing in DB.alerts.values():
        if existing.get("rule_code") != rule_code:
            continue
        if existing.get("subject_id") != subject_id:
            continue
        if existing.get("status") != "RESOLVED":
            continue
        upd = to_aware_utc(existing.get("updated_at"))
        if upd is None or upd < cutoff:
            continue
        # within 24h of resolution -> reopen
        existing["status"] = "REOPENED"
        existing["acknowledged_by"] = None
        sev, _ = compute_severity(existing, now, reconciled=False)
        existing["severity"] = sev
        bump_version(existing)
        return existing

    rec = stamp_create({
        "id": new_id(),
        "tenant_id": tenant_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "rule_code": rule_code,
        "status": "TRIGGERED",
        "acknowledged_by": None,
        "resolved_by": None,
    })
    sev, _ = compute_severity(rec, now, reconciled=False)
    rec["severity"] = sev
    DB.alerts[rec["id"]] = rec
    return rec
