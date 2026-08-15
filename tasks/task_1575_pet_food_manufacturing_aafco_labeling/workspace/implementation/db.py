"""In-memory data store. Empty on every boot -- no seeding."""

import uuid
from datetime import datetime, timezone, timedelta


class Store:
    def __init__(self):
        # Logical clock: default 2026-08-01T00:00:00Z, never wall time.
        self.logical_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

        # Entity tables: dict keyed by id
        self.brand_owners = {}
        self.suppliers = {}
        self.ingredients = {}
        self.supplier_ingredient_approvals = {}
        self.formulas = {}
        self.formula_ingredients = {}
        self.nutrient_profiles = {}
        self.feeding_trial_protocols = {}
        self.production_batches = {}
        self.batch_lot_codes = {}
        self.lab_samples = {}
        self.ga_reports = {}
        self.state_registrations = {}
        self.complaint_cases = {}
        self.recall_actions = {}

    def now(self) -> datetime:
        return self.logical_clock

    def now_iso(self) -> str:
        return iso_format(self.logical_clock)

    def advance_clock(self, to_dt: datetime):
        self.logical_clock = to_dt

    def new_id(self) -> str:
        return str(uuid.uuid4())


def iso_format(dt: datetime) -> str:
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{base}.{ms:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 datetime string into an aware datetime in UTC."""
    if isinstance(s, datetime):
        return s.astimezone(timezone.utc)
    if not isinstance(s, str):
        return None
    v = s.strip()
    # Accept trailing Z
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        # Try a few common formats
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                    "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s if not s.endswith("Z") else s[:-1],
                                       fmt.replace("%z", ""))
                break
            except ValueError:
                continue
        else:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# Global store instance (fresh per process boot)
store = Store()
