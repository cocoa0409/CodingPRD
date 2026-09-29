"""Shared lookup, filtering, ordering and pagination helpers."""
import datetime

from flask import g, request

from errors import ApiError
from response import list_response
from store import db
from util import UTC

_MIN_DT = datetime.datetime(1, 1, 1, tzinfo=UTC)

NOT_FOUND = {
    "plants": "ERR_PLANT_NOT_FOUND",
    "cell_designs": "ERR_CELL_DESIGN_NOT_FOUND",
    "workers": "ERR_WORKER_NOT_FOUND",
    "formation_bays": "ERR_FORMATION_BAY_NOT_FOUND",
    "test_chambers": "ERR_TEST_CHAMBER_NOT_FOUND",
    "production_lots": "ERR_LOT_NOT_FOUND",
    "battery_assemblies": "ERR_ASSEMBLY_NOT_FOUND",
    "formation_runs": "ERR_FORMATION_RUN_NOT_FOUND",
    "capacity_tests": "ERR_CAPACITY_TEST_NOT_FOUND",
    "chargers": "ERR_CHARGER_NOT_FOUND",
    "fleet_sizing_requests": "ERR_SIZING_REQUEST_NOT_FOUND",
    "battery_units": "ERR_BATTERY_UNIT_NOT_FOUND",
}


def lookup(collection, row_id, error_id=None):
    """Resolve a row, raising the collection's not-found error when absent."""
    record = getattr(db, collection).get(row_id) if isinstance(row_id, str) else None
    if record is None:
        raise ApiError(error_id or NOT_FOUND[collection])
    return record


def sort_key(field):
    def keyfunc(row):
        value = row.get(field)
        if value is None:
            return _MIN_DT if field.endswith("_at") else ""
        return value

    return keyfunc


def sort_rows(rows, keys):
    """Stable multi-key sort. `keys` is most-significant first."""
    ordered = list(rows)
    full = list(keys) + [("_seq", "asc")]
    for field, direction in reversed(full):
        ordered.sort(key=sort_key(field), reverse=(direction == "desc"))
    return ordered


def apply_filters(rows, filters):
    """`filters` maps query-parameter name to the row field it matches."""
    out = list(rows)
    for param, field in filters.items():
        raw = request.args.get(param)
        if raw is None:
            continue
        out = [row for row in out if _matches(row.get(field), raw)]
    return out


def _matches(value, raw):
    if value is None:
        return False
    if isinstance(value, bool):
        return str(value).lower() == raw.strip().lower()
    return str(value) == raw


def paginated(rows, keys):
    ordered = sort_rows(rows, keys)
    total = len(ordered)
    limit = getattr(g, "limit", 10)
    offset = getattr(g, "offset", 0)
    window = ordered[offset:offset + limit]
    return list_response(window, limit, offset, total)


def unique_or_conflict(collection, field, value, scope_field=None, scope_value=None):
    """Tier 9 uniqueness guard."""
    for row in getattr(db, collection).values():
        if row.get(field) != value:
            continue
        if scope_field is not None and row.get(scope_field) != scope_value:
            continue
        raise ApiError(
            "ERR_DUPLICATE_CODE",
            "%s '%s' already exists" % (field, value),
        )


def lot_of(record):
    return db.production_lots.get(record.get("lot_id"))


def plant_of_lot(lot):
    return db.plants.get(lot.get("plant_id"))


def design_of_lot(lot):
    return db.cell_designs.get(lot.get("cell_design_id"))


def assemblies_of_lot(lot_id):
    return [a for a in db.battery_assemblies.values() if a.get("lot_id") == lot_id]


def tests_of_assembly(assembly_id):
    return [t for t in db.capacity_tests.values() if t.get("assembly_id") == assembly_id]


def runs_of_lot(lot_id):
    return [r for r in db.formation_runs.values() if r.get("lot_id") == lot_id]


def lots_of_plant(plant_id):
    return [l for l in db.production_lots.values() if l.get("plant_id") == plant_id]


def units_of_plant(plant_id):
    lot_ids = {l["id"] for l in lots_of_plant(plant_id)}
    return [u for u in db.battery_units.values() if u.get("lot_id") in lot_ids]


def samples_of_worker(worker_id):
    return [s for s in db.exposure_samples.values() if s.get("worker_id") == worker_id]


def logs_of_unit(unit_id):
    return [m for m in db.maintenance_logs.values() if m.get("battery_unit_id") == unit_id]
