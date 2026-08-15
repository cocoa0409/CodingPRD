"""In-memory data store and logical clock. Fresh process => empty store.

The logical clock starts at exactly 2026-08-01T00:00:00Z (never wall clock)
and is advanced only via POST /potato-shed/_clock/set_current_utc.
"""
from datetime import datetime, timezone

STORE = {
    "growers": {},
    "sheds": {},
    "bins": {},
    "lots": {},
    "assessments": {},
    "contracts": {},
    "orders": {},
    "runs": {},
    "draws": {},
    "checks": {},
    "audits": {},
    "settlements": {},
}

CLOCK = {
    "dt": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc),
    "raw": "2026-08-01T00:00:00Z",
}
