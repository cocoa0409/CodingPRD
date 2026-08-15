"""In-memory data store. Starts empty on every boot — no seeding whatsoever.

All entities are stored as plain dicts keyed by id. The logical clock starts at
exactly 2026-08-01T00:00:00Z and only moves via POST /v1/_clock/set_current_utc;
it never falls back to wall-clock time (PRD §2.5).
"""
import uuid
from datetime import datetime, timezone


def _parse_iso(s):
    """Parse an ISO 8601 datetime string to an aware UTC datetime (second precision)."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_out(dt):
    """Serialize an aware UTC datetime as ISO 8601 with 'Z'. Second precision."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    def __init__(self):
        self.cases = {}
        self.assets = {}
        self.claims = {}
        self.engagements = {}
        self.fee_applications = {}
        self.authorization_requests = {}
        self.status_reports = {}
        self.distribution_plans = {}
        self.distribution_payments = {}
        # Logical clock: default exactly 2026-08-01T00:00:00Z
        self.logical_now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def new_id(self):
        return str(uuid.uuid4())

    def now(self):
        return self.logical_now

    def now_iso(self):
        return iso_out(self.logical_now)


store = Store()
