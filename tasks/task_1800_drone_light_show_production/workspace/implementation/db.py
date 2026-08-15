"""In-memory data store. Empty at every boot; no seeding."""

import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.sites = {}
        self.show_events = {}
        self.authorizations = {}
        self.designs = {}
        self.simulation_runs = {}
        self.safety_configs = {}
        self.drones = {}
        self.charge_bays = {}
        self.charge_sessions = {}
        self.assignments = {}
        self.weather_readings = {}
        self.evaluations = {}
        self.incident_reports = {}
        self.flight_logs = {}
        # creation-order lists per collection for stable list sorting
        self.insertion_order = {
            "sites": [],
            "show_events": [],
            "authorizations": [],
            "designs": [],
            "simulation_runs": [],
            "safety_configs": [],
            "drones": [],
            "charge_bays": [],
            "charge_sessions": [],
            "assignments": [],
            "weather_readings": [],
            "evaluations": [],
            "incident_reports": [],
            "flight_logs": [],
        }
        # logical clock (ISO string); default per PRD 2.4
        self.clock = "2026-08-01T00:00:00Z"
        # wall-clock counter to make created_at unique/monotone within a run
        self._created_seq = 0


DB = Store()


def new_id():
    return str(uuid.uuid4())


def clock_now():
    """Current logical-clock reading as a timezone-aware datetime (UTC)."""
    return parse_dt(DB.clock)


def now_iso():
    """Logical-clock reading formatted with 3 fractional digits, Z suffix."""
    return fmt_dt(clock_now())


def wall_created_at():
    """created_at/updated_at come from the logical clock (PRD 2.4/2.5).
    With the clock frozen, many entities share the same timestamp; list
    endpoints sort by insertion order (which equals creation order)."""
    return fmt_dt(clock_now())


def parse_dt(s):
    """Parse an ISO 8601 timestamp (with Z or offset) into aware datetime."""
    if isinstance(s, datetime):
        return s
    s = str(s).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Format aware datetime as ISO8601 UTC with 3 fractional digits and Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = int(round(dt.microsecond / 1000.0))
    if ms >= 1000:
        from datetime import timedelta
        dt = dt + timedelta(seconds=1)
        base = dt.strftime("%Y-%m-%dT%H:%M:%S")
        ms = 0
    return f"{base}.{ms:03d}Z"
