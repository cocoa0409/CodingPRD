"""In-memory data store. The store starts empty on every boot; no seeding."""
import uuid
from datetime import datetime, timezone

DB = {
    "team_members": {},
    "projects": {},
    "credit_library_entries": {},
    "energy_models": {},
    "credit_attempts": {},
    "review_comments": {},
    "commissioning_tasks": {},
    "incentive_programs": {},
    "project_incentives": {},
    "cost_premium_analyses": {},
    "performance_reports": {},
}

# Monotonic insertion counter -> stable created_at-tie ordering for lists.
SEQ = {"n": 0}

# Logical clock (PRD section 2.10). Startup default; never falls back to
# wall-clock time. Read by certification decisions and report tiling anchor.
CLOCK = {"current_utc": "2026-08-01T00:00:00Z"}


def new_id():
    return str(uuid.uuid4())


def next_seq():
    SEQ["n"] += 1
    return SEQ["n"]


def now_iso():
    """Wall-clock UTC timestamp, ISO 8601 with three fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"
