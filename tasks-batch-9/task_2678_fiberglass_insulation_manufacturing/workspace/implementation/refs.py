"""Foreign-key resolution (PRD 2.9) and list-endpoint filtering (PRD 2.3)."""

from flask import request

from db import store
from errors import fail


def _get(collection, key, error_id, label):
    if key is None:
        return None
    row = collection.get(key)
    if row is None:
        fail(error_id, "%s %s was not found" % (label, key))
    return row


def get_plant(pid):
    return _get(store.plants, pid, "ERR_PLANT_NOT_FOUND", "plant")


def get_program(pid):
    return _get(store.programs, pid, "ERR_CERTIFICATION_PROGRAM_NOT_FOUND", "certification program")


def get_binder(pid):
    return _get(store.binders, pid, "ERR_BINDER_FORMULATION_NOT_FOUND", "binder formulation")


def get_product_line(pid):
    return _get(store.product_lines, pid, "ERR_PRODUCT_LINE_NOT_FOUND", "product line")


def get_run(pid):
    return _get(store.runs, pid, "ERR_PRODUCTION_RUN_NOT_FOUND", "production run")


def get_changeover(pid):
    return _get(store.changeovers, pid, "ERR_CHANGEOVER_EVENT_NOT_FOUND", "changeover event")


def get_thermal_test(pid):
    return _get(store.thermal_tests, pid, "ERR_THERMAL_TEST_NOT_FOUND", "thermal test")


def get_lot(pid):
    return _get(store.lots, pid, "ERR_INVENTORY_LOT_NOT_FOUND", "inventory lot")


def get_cycle(pid):
    return _get(store.cycles, pid, "ERR_ALLOCATION_CYCLE_NOT_FOUND", "allocation cycle")


def get_order(pid):
    return _get(store.orders, pid, "ERR_CHANNEL_ORDER_NOT_FOUND", "channel order")


def get_line(pid):
    return _get(store.lines, pid, "ERR_ALLOCATION_LINE_NOT_FOUND", "allocation line")


def get_batch(pid):
    return _get(store.cullet, pid, "ERR_CULLET_BATCH_NOT_FOUND", "cullet batch")


_SENTINEL = object()


def _matches(row, key, raw, kind):
    value = row.get(key)
    if kind == "bool":
        text = raw.strip().lower()
        if text not in ("true", "false"):
            return False
        return value is True if text == "true" else value is False
    if kind == "int":
        try:
            wanted = int(raw.strip(), 10)
        except (TypeError, ValueError):
            return False
        return value == wanted
    return value is not None and str(value) == raw


def apply_filters(rows, spec):
    """spec: {query_param: (row_key, kind)} with kind in str|bool|int."""
    result = list(rows)
    for param, (key, kind) in spec.items():
        raw = request.args.get(param)
        if raw is None or raw == "":
            continue
        result = [r for r in result if _matches(r, key, raw, kind)]
    return result
