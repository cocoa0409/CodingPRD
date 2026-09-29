"""In-memory data store.

Every table starts empty on every boot: nothing is seeded, preloaded or
hardcoded. Tests build all preconditions through the declared API surface.
"""
import uuid

import clock

aircraft = {}
compartments = {}
runways = {}
performance_bands = {}
weight_programs = {}
flights = {}
load_plans = {}
pax_lines = {}
bag_allocations = {}
cargo_items = {}
hazmat_declarations = {}
load_sheets = {}
last_minute_changes = {}
load_audits = {}

_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def insert(table, data):
    row = dict(data)
    row["id"] = str(uuid.uuid4())
    now = clock.now_iso()
    row["created_at"] = now
    row["updated_at"] = now
    row["version"] = 1
    row["_seq"] = next_seq()
    table[row["id"]] = row
    return row


def touch(row):
    """Refresh updated_at and increment version by exactly 1 (PRD §2.4)."""
    row["updated_at"] = clock.now_iso()
    row["version"] = int(row["version"]) + 1
    return row


def public(row):
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def ordered(rows):
    """Default list ordering: created_at ascending (insertion order breaks ties)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ----------------------------------------------------------------- lookups
def children(table, field, value):
    return ordered([r for r in table.values() if r.get(field) == value])


def plan_pax_lines(plan_id):
    return children(pax_lines, "load_plan_id", plan_id)


def plan_bag_allocations(plan_id):
    return children(bag_allocations, "load_plan_id", plan_id)


def flight_cargo(flight_id):
    return children(cargo_items, "flight_id", flight_id)


def flight_plans(flight_id):
    return children(load_plans, "flight_id", flight_id)


def plan_sheets(plan_id):
    return children(load_sheets, "load_plan_id", plan_id)


def sheet_changes(sheet_id):
    return children(last_minute_changes, "load_sheet_id", sheet_id)


def cargo_declarations(cargo_item_id):
    return children(hazmat_declarations, "cargo_item_id", cargo_item_id)


def flight_audits(flight_id):
    return children(load_audits, "flight_id", flight_id)


def flight_declarations(flight_id):
    """Every hazmat declaration attached to any consignment of the flight."""
    cargo_ids = {c["id"] for c in cargo_items.values() if c["flight_id"] == flight_id}
    return ordered([d for d in hazmat_declarations.values() if d["cargo_item_id"] in cargo_ids])
