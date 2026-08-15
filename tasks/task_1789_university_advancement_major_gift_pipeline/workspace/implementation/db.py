"""In-memory data store. Starts empty on every boot; nothing is seeded."""

from datetime import datetime, timezone

# Logical clock: starts at exactly 2026-08-01T00:00:00Z and only moves forward
# via POST /advancement/_clock/set_current_utc. Never falls back to wall clock.
START_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

clock = {"now": START_UTC}

store = {
    "fundraisers": {},
    "prospects": {},
    "assessments": {},
    "assignments": {},
    "proposals": {},
    "naming_opportunities": {},
    "agreements": {},
    "funds": {},
    "pledges": {},
    "installments": {},
    "write_offs": {},
    "payments": {},
    "campaigns": {},
    "credit_splits": {},
    "reports": {},
    "societies": {},
}
