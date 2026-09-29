"""Lookup and list helpers shared by the route modules."""
import store
import validate
from errors import (
    ERR_ALLOCATION_NOT_FOUND,
    ERR_BATCH_NOT_FOUND,
    ERR_CATALYST_CHARGE_NOT_FOUND,
    ERR_CONTRACT_NOT_FOUND,
    ERR_CREDIT_BLOCK_NOT_FOUND,
    ERR_HEDGE_POSITION_NOT_FOUND,
    ERR_LOT_NOT_FOUND,
    ERR_NOMINATION_NOT_FOUND,
    ERR_PATHWAY_NOT_FOUND,
    ERR_RUN_NOT_FOUND,
    ERR_SUPPLIER_NOT_FOUND,
    ERR_TURNAROUND_WINDOW_NOT_FOUND,
    ERR_UNIT_NOT_FOUND,
    fail,
)

_TABLES = {
    "supplier": (lambda: store.suppliers, ERR_SUPPLIER_NOT_FOUND, "Supplier"),
    "lot": (lambda: store.lots, ERR_LOT_NOT_FOUND, "Feedstock lot"),
    "unit": (lambda: store.units, ERR_UNIT_NOT_FOUND, "Hydrotreating unit"),
    "charge": (lambda: store.charges, ERR_CATALYST_CHARGE_NOT_FOUND, "Catalyst charge"),
    "window": (lambda: store.windows, ERR_TURNAROUND_WINDOW_NOT_FOUND, "Turnaround window"),
    "contract": (lambda: store.contracts, ERR_CONTRACT_NOT_FOUND, "Hydrogen contract"),
    "nomination": (lambda: store.nominations, ERR_NOMINATION_NOT_FOUND, "Hydrogen nomination"),
    "run": (lambda: store.runs, ERR_RUN_NOT_FOUND, "Processing run"),
    "allocation": (lambda: store.allocations, ERR_ALLOCATION_NOT_FOUND, "Feedstock allocation"),
    "batch": (lambda: store.batches, ERR_BATCH_NOT_FOUND, "Product batch"),
    "pathway": (lambda: store.pathways, ERR_PATHWAY_NOT_FOUND, "Pathway registration"),
    "block": (lambda: store.blocks, ERR_CREDIT_BLOCK_NOT_FOUND, "Credit block"),
    "hedge": (lambda: store.hedges, ERR_HEDGE_POSITION_NOT_FOUND, "Hedge position"),
}


def find(kind, row_id):
    getter, error_id, label = _TABLES[kind]
    table = getter()
    if not isinstance(row_id, str):
        fail(error_id, "%s not found." % label)
    row = table.get(row_id)
    if row is None:
        fail(error_id, "%s %s not found." % (label, row_id))
    return row


def body_ref(kind, data, field):
    """Rung 4: a body identifier must resolve to an existing row."""
    getter, error_id, label = _TABLES[kind]
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        fail(error_id, "%s referenced by '%s' not found." % (label, field))
    row = getter().get(value)
    if row is None:
        fail(error_id, "%s %s not found." % (label, value))
    return row


def listing(rows, filters=None):
    """Apply equality filters from the query string, then paginate."""
    limit, offset = validate.pagination()
    if filters:
        for arg_name, field in filters.items():
            raw = validate.arg(arg_name)
            if raw is None:
                continue
            rows = [r for r in rows if _matches(r.get(field), raw)]
    return rows, limit, offset


def _matches(value, raw):
    if isinstance(value, bool):
        lowered = raw.strip().lower()
        if lowered in ("true", "1"):
            return value is True
        if lowered in ("false", "0"):
            return value is False
        return False
    if value is None:
        return False
    return str(value) == raw
