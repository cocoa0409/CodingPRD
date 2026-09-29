"""Row lookup — ladder rungs 4 and 5 (PRD §2.9). Each miss is its own 404."""

from db import db
from errors import ApiError


def _get(table, row_id, error_id):
    if not isinstance(row_id, str) or not row_id:
        raise ApiError(error_id)
    row = table.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def program(program_id):
    return _get(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")


def specification(specification_id):
    return _get(db.specifications, specification_id, "ERR_SPECIFICATION_NOT_FOUND")


def clause(clause_id):
    return _get(db.clauses, clause_id, "ERR_CLAUSE_NOT_FOUND")


def compliance_entry(entry_id):
    return _get(db.compliance_entries, entry_id, "ERR_COMPLIANCE_ENTRY_NOT_FOUND")


def unit_order(unit_order_id):
    return _get(db.unit_orders, unit_order_id, "ERR_UNIT_ORDER_NOT_FOUND")


def slot_line(slot_line_id):
    return _get(db.slot_lines, slot_line_id, "ERR_SLOT_LINE_NOT_FOUND")


def reservation(reservation_id):
    return _get(db.reservations, reservation_id, "ERR_RESERVATION_NOT_FOUND")


def plant_bay(plant_bay_id):
    return _get(db.plant_bays, plant_bay_id, "ERR_PLANT_BAY_NOT_FOUND")


def inspection_trip(trip_id):
    return _get(db.trips, trip_id, "ERR_INSPECTION_TRIP_NOT_FOUND")


def change_order(change_order_id):
    return _get(db.change_orders, change_order_id, "ERR_CHANGE_ORDER_NOT_FOUND")


def certification_test(test_id):
    return _get(db.certification_tests, test_id, "ERR_CERTIFICATION_TEST_NOT_FOUND")


def warranty_startup(warranty_id):
    return _get(db.warranty_startups, warranty_id, "ERR_WARRANTY_STARTUP_NOT_FOUND")
