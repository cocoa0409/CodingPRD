"""In-memory data store. Empty on every boot — no seeding."""
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# Stores keyed by id
asset_classes = {}
capital_projects = {}
cip_cost_lines = {}
fixed_assets = {}
depreciation_runs = {}
depreciation_entries = {}
disposals = {}
inventory_runs = {}
inventory_count_lines = {}
impairment_reviews = {}
external_schedules = {}


def reset_all():
    """Clear every store (used at startup to guarantee empty state)."""
    for store in (asset_classes, capital_projects, cip_cost_lines, fixed_assets,
                  depreciation_runs, depreciation_entries, disposals,
                  inventory_runs, inventory_count_lines, impairment_reviews,
                  external_schedules):
        store.clear()
