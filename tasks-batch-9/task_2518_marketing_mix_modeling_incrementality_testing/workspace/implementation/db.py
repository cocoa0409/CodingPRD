"""In-memory data store. Empty on every boot — nothing is ever seeded."""

import uuid
from datetime import datetime, timezone

# PRD section 2.3: the logical clock starts at exactly this instant on every boot.
CLOCK_DEFAULT_RAW = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "markets",
    "media_channels",
    "geo_cells",
    "data_windows",
    "spend_observations",
    "sales_observations",
    "model_runs",
    "channel_contributions",
    "experiments",
    "calibration_records",
    "budget_scenarios",
    "budget_allocations",
    "reconciliation_reports",
)


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_DEFAULT
        self.clock_raw = CLOCK_DEFAULT_RAW

    def all(self, name):
        return list(getattr(self, name).values())

    def add(self, name, row):
        getattr(self, name)[row["id"]] = row
        return row


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    dt = datetime.now(timezone.utc)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def base_row(kind):
    stamp = now_iso()
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_kind": kind,
    }


def touch(row):
    """Every mutation — direct or cascade-induced — refreshes updated_at and bumps version."""
    row["updated_at"] = now_iso()
    row["version"] = row["version"] + 1
    return row


# ---------------------------------------------------------------- lookups

def find(name, row_id):
    return getattr(db, name).get(row_id)


def channels_of_market(market_id):
    return [c for c in db.all("media_channels") if c["market_id"] == market_id]


def cells_of_market(market_id):
    return [c for c in db.all("geo_cells") if c["market_id"] == market_id]


def windows_of_market(market_id):
    return [w for w in db.all("data_windows") if w["market_id"] == market_id]


def runs_of_market(market_id):
    return [r for r in db.all("model_runs") if r["market_id"] == market_id]


def runs_of_window(window_id):
    return [r for r in db.all("model_runs") if r["data_window_id"] == window_id]


def contributions_of_run(run_id, current_only=False):
    rows = [c for c in db.all("channel_contributions") if c["model_run_id"] == run_id]
    if current_only:
        rows = [c for c in rows if c["is_current"]]
    return rows


def scenarios_of_market(market_id):
    return [s for s in db.all("budget_scenarios") if s["market_id"] == market_id]


def scenarios_of_run(run_id):
    return [s for s in db.all("budget_scenarios") if s["model_run_id"] == run_id]


def allocations_of_scenario(scenario_id):
    return [a for a in db.all("budget_allocations") if a["budget_scenario_id"] == scenario_id]


def reports_of_run(run_id):
    return [r for r in db.all("reconciliation_reports") if r["model_run_id"] == run_id]


def calibration_records_of_run(run_id, live_only=False):
    rows = [c for c in db.all("calibration_records") if c["model_run_id"] == run_id]
    if live_only:
        rows = [c for c in rows if not c["superseded"]]
    return rows


def spend_of_window(window_id, include_superseded=False):
    rows = [s for s in db.all("spend_observations") if s["data_window_id"] == window_id]
    if not include_superseded:
        rows = [s for s in rows if s["superseded_by_id"] is None]
    return rows


def sales_of_window(window_id):
    return [s for s in db.all("sales_observations") if s["data_window_id"] == window_id]


def published_run_of_market(market_id):
    for r in runs_of_market(market_id):
        if r["publication_status"] == "PUBLISHED":
            return r
    return None
