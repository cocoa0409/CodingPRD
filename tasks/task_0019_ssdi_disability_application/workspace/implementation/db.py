"""In-memory data store + timestamp utilities + clock."""
import uuid
from datetime import datetime, timezone


# Tables: id -> dict
claimants = {}
work_credits = {}
applications = {}
medical_evidence = {}
medical_decisions = {}
hearings = {}
awards = {}
child_aux = {}
ssi_supplements = {}
cdr_reviews = {}


# Logical server clock. None => real wall-clock; otherwise a fixed datetime (UTC).
_clock_override = None


def reset_all():
    """Clear every table (used only in tests; safe at module import too)."""
    global _clock_override
    for d in (
        claimants,
        work_credits,
        applications,
        medical_evidence,
        medical_decisions,
        hearings,
        awards,
        child_aux,
        ssi_supplements,
        cdr_reviews,
    ):
        d.clear()
    _clock_override = None


def now_utc() -> datetime:
    """Server's notion of NOW (UTC, tz-aware)."""
    if _clock_override is not None:
        return _clock_override
    return datetime.now(timezone.utc)


def set_clock(dt: datetime):
    """Pin server clock to dt (must be tz-aware UTC)."""
    global _clock_override
    _clock_override = dt


def new_id() -> str:
    return str(uuid.uuid4())


def iso_now() -> str:
    n = now_utc()
    if n.tzinfo is None:
        n = n.replace(tzinfo=timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def stamp_create(rec: dict, with_version: bool = True) -> dict:
    """Stamp id/created_at/updated_at/version=1 on a brand-new record."""
    if "id" not in rec:
        rec["id"] = new_id()
    ts = iso_now()
    rec.setdefault("created_at", ts)
    rec["updated_at"] = ts
    if with_version:
        rec["version"] = 1
    return rec


def stamp_update(rec: dict, with_version: bool = True) -> dict:
    """Bump updated_at and version on a mutated record."""
    rec["updated_at"] = iso_now()
    if with_version and "version" in rec:
        rec["version"] = rec["version"] + 1
    return rec
