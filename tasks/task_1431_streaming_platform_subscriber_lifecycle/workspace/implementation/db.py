"""In-memory data store. Starts empty on every boot - no seeding."""

# Entity stores keyed by ID
plans = {}
accounts = {}
profiles = {}
subscriptions = {}
billing_events = {}
save_offers = {}
price_change_notices = {}
winback_campaigns = {}
partner_billing_records = {}
signup_attributions = {}

# Logical clock - default startup time per PRD §2.4
# Server default: 2026-08-01T00:00:00Z; never falls back to wall clock.
from datetime import datetime, timezone

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_now = DEFAULT_NOW


def get_now():
    return _now


def set_now(dt):
    global _now
    _now = dt
