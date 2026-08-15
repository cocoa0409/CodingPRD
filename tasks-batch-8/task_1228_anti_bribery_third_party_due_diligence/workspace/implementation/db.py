"""In-memory data store. Starts empty on every boot — no seeding."""

from datetime import datetime, timezone, date


def new_store():
    return {
        "country_risk_profiles": {},      # id -> record
        "country_code_index": {},          # country_code -> id
        "risk_scoring_policies": {},       # id -> record
        "third_parties": {},               # id -> record
        "screening_checks": {},            # id -> record
        "questionnaires": {},              # id -> record
        "red_flags": {},                   # id -> record
        "escalation_cases": {},            # id -> record
        "contracts": {},                   # id -> record
        "certifications": {},              # id -> record
        "payment_requests": {},            # id -> record
        "gift_entries": {},                # id -> record
        "rediligence_cycles": {},          # id -> record
        "audit_exercises": {},             # id -> record
        "training_assignments": {},        # id -> record
        # logical clock: startup default exactly 2026-05-01T00:00:00Z
        "clock": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc),
    }


DB = new_store()


def current_dt():
    return DB["clock"]


def current_date():
    return DB["clock"].date()


def now_iso():
    """Wall-clock timestamp for response meta (3 fractional digits)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def logical_iso():
    """Logical-clock timestamp for created_at/updated_at on domain records.

    PRD §2.5: all date-sensitive behavior reads from the logical clock.
    """
    now = DB["clock"]
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def iso_date(d):
    return d.isoformat() if isinstance(d, date) else d
