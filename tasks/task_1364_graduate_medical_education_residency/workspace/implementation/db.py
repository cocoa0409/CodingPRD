"""In-memory data store. The store starts empty on every boot; no seeding."""
import itertools
import uuid
from datetime import datetime, timezone

DB = {
    "programs": {},
    "academic_years": {},
    "schedule_blocks": {},
    "complement_approvals": {},
    "residents": {},
    "rotations": {},
    "rotation_assignments": {},
    "duty_hour_logs": {},
    "duty_hour_violations": {},
    "moonlighting_requests": {},
    "milestone_evaluations": {},
    "ccc_reviews": {},
    "procedure_case_logs": {},
    "case_requirements": {},
    "remediation_plans": {},
    "probation_cases": {},
    "accreditation_citations": {},
    "annual_surveys": {},
}

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Logical clock (PRD section 2.4). Never falls back to wall-clock time.
CLOCK = {
    "dt": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc),
    "raw": DEFAULT_CLOCK_ISO,
}

_seq = itertools.count(1)


def next_seq():
    """Global insertion sequence for deterministic created_at ordering."""
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock UTC timestamp, ISO 8601 with three fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def clock_dt():
    return CLOCK["dt"]


def clock_date_str():
    """Date portion of the logical clock as YYYY-MM-DD."""
    return CLOCK["dt"].strftime("%Y-%m-%d")


def fmt_clock(dt):
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        base += f".{dt.microsecond // 1000:03d}"
    return base + "Z"
