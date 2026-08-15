"""In-memory data store. Everything lives in module-level dicts keyed by id.
A fresh process starts completely empty — no seeding anywhere."""

import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5). Before being set it reads exactly
# 2026-08-01T00:00:00Z — a fixed startup default, never wall clock.
# ---------------------------------------------------------------------------
_CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"


def _parse_iso(s):
    if isinstance(s, datetime):
        return s
    if not isinstance(s, str):
        raise ValueError("not an ISO timestamp")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fmt_iso(dt):
    """ISO 8601 UTC with three fractional digits, trailing Z."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.microsecond // 1000:03d}Z"


class _Clock:
    def __init__(self):
        self._now = _parse_iso(_CLOCK_DEFAULT_ISO)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = _Clock()

# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------
conventions = {}
category_quotas = {}
space_units = {}
exhibitors = {}
applications = {}
jury_scores = {}
placements = {}
neighbor_requests = {}
staff_members = {}
load_slots = {}
dock_doors = {}
freight_bookings = {}
issue_tickets = {}
sales_reports = {}


def new_id():
    return str(uuid.uuid4())


def now_dt():
    return clock.now()


def now_iso():
    return _fmt_iso(clock.now())


def stamp_created(rec):
    ts = now_iso()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
