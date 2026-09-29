"""Row resolution helpers. Each raises the entity's own 404 code (PRD 2.6)."""
from db import store
from errors import api_error


def _get(collection, row_id, error_id):
    row = collection.get(row_id)
    if row is None:
        raise api_error(error_id, "No such resource.")
    return row


def outage(row_id):
    return _get(store.outages, row_id, "ERR_OUTAGE_NOT_FOUND")


def spent_fuel_pool(row_id):
    return _get(store.spent_fuel_pools, row_id, "ERR_SPENT_FUEL_POOL_NOT_FOUND")


def rad_area(row_id):
    return _get(store.rad_areas, row_id, "ERR_RAD_AREA_NOT_FOUND")


def safety_function(row_id):
    return _get(store.safety_functions, row_id, "ERR_SAFETY_FUNCTION_NOT_FOUND")


def work_order(row_id):
    return _get(store.work_orders, row_id, "ERR_WORK_ORDER_NOT_FOUND")


def schedule_activity(row_id):
    return _get(store.schedule_activities, row_id, "ERR_SCHEDULE_ACTIVITY_NOT_FOUND")


def core_load_pattern(row_id):
    return _get(store.core_load_patterns, row_id, "ERR_CORE_LOAD_PATTERN_NOT_FOUND")


def pool_cell_reservation(row_id):
    return _get(store.pool_cell_reservations, row_id, "ERR_POOL_RESERVATION_NOT_FOUND")


def supplemental_worker(row_id):
    return _get(store.supplemental_workers, row_id, "ERR_WORKER_NOT_FOUND")


def rwp(row_id):
    return _get(store.rwps, row_id, "ERR_RWP_NOT_FOUND")


def emergent_item(row_id):
    return _get(store.emergent_items, row_id, "ERR_EMERGENT_ITEM_NOT_FOUND")


def startup_test(row_id):
    return _get(store.startup_tests, row_id, "ERR_STARTUP_TEST_NOT_FOUND")
