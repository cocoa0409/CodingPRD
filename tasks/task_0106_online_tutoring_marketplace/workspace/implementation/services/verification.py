"""Tutor verification posture computation and credential-driven cascades."""

from clock import clock, parse_iso
from config import CRITICAL_CREDENTIAL_TYPES
from db import db, touch


def _tutor_credentials(tutor_id):
    return [c for c in db.credentials.values() if c["tutor_id"] == tutor_id]


def compute_verification_posture(tutor):
    """Apply the deterministic precedence rule:
    REJECTED > VERIFIED > PENDING_REVIEW > SUSPENDED > UNVERIFIED.
    """
    now = clock.now()
    creds = _tutor_credentials(tutor["id"])

    # 1. Any critical-type credential REJECTED => REJECTED
    for c in creds:
        if c["status"] == "REJECTED" and c["credential_type"] in CRITICAL_CREDENTIAL_TYPES:
            return "REJECTED"

    # 2. Approved-and-unexpired set
    approved_types = set()
    for c in creds:
        if c["status"] != "APPROVED":
            continue
        if c.get("expires_at"):
            expires = parse_iso(c["expires_at"])
            if expires <= now:
                continue
        approved_types.add(c["credential_type"])
    if CRITICAL_CREDENTIAL_TYPES.issubset(approved_types):
        return "VERIFIED"

    # 3. Any SUBMITTED => PENDING_REVIEW
    if any(c["status"] == "SUBMITTED" for c in creds):
        return "PENDING_REVIEW"

    # 4. If previously VERIFIED but no longer => SUSPENDED
    if tutor.get("verification_status") == "VERIFIED":
        return "SUSPENDED"

    return "UNVERIFIED"


def recompute_tutor_verification(tutor):
    """Apply posture; if status changed, bump tutor record. Returns the new status."""
    new_status = compute_verification_posture(tutor)
    if new_status != tutor.get("verification_status"):
        previous = tutor.get("verification_status")
        tutor["verification_status"] = new_status
        touch(tutor)
        # Cascade: if dropped to SUSPENDED or REJECTED, cancel future CONFIRMED sessions
        if new_status in ("SUSPENDED", "REJECTED") and previous == "VERIFIED":
            cascade_cancel_future_confirmed_for_tutor(tutor["id"])
    return new_status


def cascade_cancel_future_confirmed_for_tutor(tutor_id):
    """Cancel all CONFIRMED future-dated sessions of a tutor with full refund."""
    from services.sessions import force_cancel_session_by_tutor_cascade
    now = clock.now()
    affected = []
    for s in list(db.sessions.values()):
        if s["tutor_id"] != tutor_id:
            continue
        if s["status"] != "CONFIRMED":
            continue
        start_at = parse_iso(s["start_at"])
        if start_at > now:
            affected.append(s)
    # Sort deterministically
    affected.sort(key=lambda r: r["id"])
    for s in affected:
        force_cancel_session_by_tutor_cascade(s)


def expire_due_credentials():
    """Sweep: credentials whose expires_at <= now go EXPIRED, then per-tutor recompute."""
    now = clock.now()
    affected_tutor_ids = set()
    for c in list(db.credentials.values()):
        if c["status"] != "APPROVED":
            continue
        if not c.get("expires_at"):
            continue
        expires = parse_iso(c["expires_at"])
        if expires <= now:
            c["status"] = "EXPIRED"
            touch(c)
            affected_tutor_ids.add(c["tutor_id"])
    for tid in sorted(affected_tutor_ids):
        tutor = db.tutors.get(tid)
        if tutor is not None:
            recompute_tutor_verification(tutor)
