"""In-memory store. Every byte of state vanishes with the process.

The store starts EMPTY on every boot: nothing is seeded, preloaded or
hardcoded. Tests build all state through the declared endpoints.
"""

import itertools
import uuid

import clock
from errors import fail

projects = {}
grading_areas = {}
yard_zones = {}
deliveries = {}
blocks = {}
piles = {}
circuits = {}
substations = {}
outage_windows = {}
tests = {}
intervals = {}
punch_items = {}
payroll_weeks = {}
labor_entries = {}

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def base(versioned=True):
    stamp = clock.now()
    row = {"id": new_id(), "created_at": stamp}
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = next(_seq)
    return row


def touch(entity):
    entity["updated_at"] = clock.now()
    entity["version"] = entity.get("version", 0) + 1


def ordered(rows):
    """created_at ascending, insertion sequence as the tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def children(collection, field, value):
    return ordered([r for r in collection.values() if r.get(field) == value])


def require(collection, ident, error_id):
    row = collection.get(ident)
    if row is None:
        fail(error_id)
    return row


def require_project(project_id):
    return require(projects, project_id, "ERR_PROJECT_NOT_FOUND")


def require_grading_area(ident):
    return require(grading_areas, ident, "ERR_GRADING_AREA_NOT_FOUND")


def require_yard_zone(ident):
    return require(yard_zones, ident, "ERR_YARD_ZONE_NOT_FOUND")


def require_delivery(ident):
    return require(deliveries, ident, "ERR_DELIVERY_NOT_FOUND")


def require_block(ident):
    return require(blocks, ident, "ERR_BLOCK_NOT_FOUND")


def require_pile(ident):
    return require(piles, ident, "ERR_PILE_NOT_FOUND")


def require_circuit(ident):
    return require(circuits, ident, "ERR_STRING_CIRCUIT_NOT_FOUND")


def require_substation(ident):
    return require(substations, ident, "ERR_SUBSTATION_NOT_FOUND")


def require_outage_window(ident):
    return require(outage_windows, ident, "ERR_OUTAGE_WINDOW_NOT_FOUND")


def require_test(ident):
    return require(tests, ident, "ERR_COMMISSIONING_TEST_NOT_FOUND")


def require_punch_item(ident):
    return require(punch_items, ident, "ERR_PUNCH_ITEM_NOT_FOUND")


def require_payroll_week(ident):
    return require(payroll_weeks, ident, "ERR_PAYROLL_WEEK_NOT_FOUND")


def require_labor_entry(ident):
    return require(labor_entries, ident, "ERR_LABOR_ENTRY_NOT_FOUND")
