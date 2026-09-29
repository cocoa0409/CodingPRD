"""Path and body identifier resolution (PRD §2.8, priorities 4 and 5)."""
import db
import errors
from errors import fail


def _get(table, row_id, error_id):
    row = table.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        fail(error_id)
    return row


def aircraft(row_id):
    return _get(db.aircraft, row_id, errors.ERR_AIRCRAFT_NOT_FOUND)


def compartment(row_id):
    return _get(db.compartments, row_id, errors.ERR_COMPARTMENT_NOT_FOUND)


def runway(row_id):
    return _get(db.runways, row_id, errors.ERR_RUNWAY_NOT_FOUND)


def performance_band(row_id):
    return _get(db.performance_bands, row_id, errors.ERR_PERFORMANCE_BAND_NOT_FOUND)


def weight_program(row_id):
    return _get(db.weight_programs, row_id, errors.ERR_WEIGHT_PROGRAM_NOT_FOUND)


def flight(row_id):
    return _get(db.flights, row_id, errors.ERR_FLIGHT_NOT_FOUND)


def load_plan(row_id):
    return _get(db.load_plans, row_id, errors.ERR_LOAD_PLAN_NOT_FOUND)


def pax_line(row_id):
    return _get(db.pax_lines, row_id, errors.ERR_PAX_LINE_NOT_FOUND)


def bag_allocation(row_id):
    return _get(db.bag_allocations, row_id, errors.ERR_BAG_ALLOCATION_NOT_FOUND)


def cargo_item(row_id):
    return _get(db.cargo_items, row_id, errors.ERR_CARGO_ITEM_NOT_FOUND)


def declaration(row_id):
    return _get(db.hazmat_declarations, row_id, errors.ERR_DECLARATION_NOT_FOUND)


def load_sheet(row_id):
    return _get(db.load_sheets, row_id, errors.ERR_LOAD_SHEET_NOT_FOUND)


def last_minute_change(row_id):
    return _get(db.last_minute_changes, row_id, errors.ERR_LAST_MINUTE_CHANGE_NOT_FOUND)


def load_audit(row_id):
    return _get(db.load_audits, row_id, errors.ERR_AUDIT_NOT_FOUND)
