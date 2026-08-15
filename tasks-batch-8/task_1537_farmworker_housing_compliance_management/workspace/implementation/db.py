"""In-memory data store. Boot empty on every process start — no seeding."""

import uuid
from datetime import datetime, timezone


def _new_id():
    return str(uuid.uuid4())


def _now_iso():
    """ISO 8601 UTC timestamp with three fractional digits."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# Entity stores: dicts keyed by id. All start empty.
sites = {}
season_windows = {}
buildings = {}
units = {}
certifications = {}
households = {}
household_members = {}
tenancies = {}
ledger_entries = {}
deduction_authorizations = {}
work_orders = {}
pest_treatments = {}
complaints = {}
regulatory_inspections = {}
service_referrals = {}


def new_id():
    return _new_id()


def now_ts():
    """Current wall-clock timestamp for created_at/updated_at (ISO 8601 UTC, 3 frac digits)."""
    return _utc_now()
