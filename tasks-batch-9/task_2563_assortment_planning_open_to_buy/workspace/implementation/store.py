"""In-memory data store and the server's logical clock (§2.6).

The store is EMPTY on every boot: no entity is ever seeded, preloaded or
hardcoded.  Every row is created through a declared endpoint.
"""
from datetime import datetime, timezone

from common import fail, new_id, now_iso, parse_dt

CLOCK_STARTUP = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.departments = {}
        self.categories = {}
        self.clusters = {}
        self.vendors = {}
        self.vauths = {}
        self.plans = {}
        self.months = {}
        self.optionplans = {}
        self.sizecells = {}
        self.items = {}
        self.commitments = {}
        self.actuals = {}
        self.cycles = {}
        self.decisions = {}
        self.overlays = {}
        self.clock = CLOCK_STARTUP
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------
def make_row(governed=True, **fields):
    """Create a row with §2.4 audit fields.  governed=False -> id/created_at only."""
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = now_iso()
    if governed:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """A mutation: refresh updated_at and advance version by exactly 1 (§2.4)."""
    row["updated_at"] = now_iso()
    row["version"] = row.get("version", 0) + 1
    return row


def by_seq(rows):
    return sorted(rows, key=lambda r: r["_seq"])


# ---------------------------------------------------------------------------
# Lookups.  Each raises the entity's own not-found code (§2.7).
# ---------------------------------------------------------------------------
def _get(table, row_id, error_id):
    if not isinstance(row_id, str):
        fail(error_id)
    row = table.get(row_id)
    if row is None:
        fail(error_id)
    return row


def get_department(i):
    return _get(db.departments, i, "ERR_DEPARTMENT_NOT_FOUND")


def get_category(i):
    return _get(db.categories, i, "ERR_CATEGORY_NOT_FOUND")


def get_cluster(i):
    return _get(db.clusters, i, "ERR_STORE_CLUSTER_NOT_FOUND")


def get_vendor(i):
    return _get(db.vendors, i, "ERR_VENDOR_NOT_FOUND")


def get_vauth(i):
    return _get(db.vauths, i, "ERR_VENDOR_AUTHORIZATION_NOT_FOUND")


def get_plan(i):
    return _get(db.plans, i, "ERR_CATEGORY_PLAN_NOT_FOUND")


def get_month(i):
    return _get(db.months, i, "ERR_PLAN_MONTH_NOT_FOUND")


def get_optionplan(i):
    return _get(db.optionplans, i, "ERR_OPTION_PLAN_NOT_FOUND")


def get_item(i):
    return _get(db.items, i, "ERR_ASSORTMENT_ITEM_NOT_FOUND")


def get_commitment(i):
    return _get(db.commitments, i, "ERR_RECEIPT_COMMITMENT_NOT_FOUND")


def get_cycle(i):
    return _get(db.cycles, i, "ERR_REFORECAST_CYCLE_NOT_FOUND")


def get_decision(i):
    return _get(db.decisions, i, "ERR_CHASE_CANCEL_DECISION_NOT_FOUND")


def get_overlay(i):
    return _get(db.overlays, i, "ERR_LOCALIZATION_OVERLAY_NOT_FOUND")


# ---------------------------------------------------------------------------
# Relationship navigation
# ---------------------------------------------------------------------------
def plan_months(plan_id):
    return sorted((m for m in db.months.values() if m["category_plan_id"] == plan_id),
                  key=lambda m: (m["month_index"], m["_seq"]))


def plan_optionplans(plan_id):
    return by_seq([c for c in db.optionplans.values() if c["category_plan_id"] == plan_id])


def plan_overlays(plan_id):
    return by_seq([o for o in db.overlays.values() if o["category_plan_id"] == plan_id])


def plan_cycles(plan_id):
    return by_seq([c for c in db.cycles.values() if c["category_plan_id"] == plan_id])


def cycle_decisions(cycle_id):
    return by_seq([d for d in db.decisions.values() if d["reforecast_cycle_id"] == cycle_id])


def optionplan_sizecells(option_plan_id):
    return sorted((s for s in db.sizecells.values() if s["option_plan_id"] == option_plan_id),
                  key=lambda s: (s["size_sort_order"], s["_seq"]))


def optionplan_items(option_plan_id):
    return by_seq([i for i in db.items.values() if i["option_plan_id"] == option_plan_id])


def month_commitments(month_id):
    return by_seq([c for c in db.commitments.values() if c["plan_month_id"] == month_id])


def item_commitments(item_id):
    return by_seq([c for c in db.commitments.values() if c["assortment_item_id"] == item_id])


def month_actuals(month_id):
    return sorted((a for a in db.actuals.values() if a["plan_month_id"] == month_id),
                  key=lambda a: (a["week_index"], a["_seq"]))


def plan_items(plan_id):
    cell_ids = set(c["id"] for c in db.optionplans.values()
                   if c["category_plan_id"] == plan_id)
    return by_seq([i for i in db.items.values() if i["option_plan_id"] in cell_ids])


def item_plan(item):
    """The CategoryPlan governing an AssortmentItem."""
    cell = db.optionplans.get(item["option_plan_id"])
    if cell is None:
        return None
    return db.plans.get(cell["category_plan_id"])


def month_plan(month):
    return db.plans.get(month["category_plan_id"])


def plan_category(plan):
    return db.categories.get(plan["category_id"])


def clock():
    return db.clock


def clock_iso():
    from common import iso_ms
    return iso_ms(db.clock)


def dt(value):
    return parse_dt(value)
