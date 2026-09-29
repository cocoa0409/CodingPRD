"""Existence resolution (ladder rung 5) and shared list plumbing."""
import db
from errors import ApiError
from response import ok, ok_list, paginate

NOT_FOUND = {
    "customer_accounts": "ERR_CUSTOMER_ACCOUNT_NOT_FOUND",
    "model_specs": "ERR_MODEL_SPEC_NOT_FOUND",
    "approved_parts": "ERR_APPROVED_PART_NOT_FOUND",
    "test_benches": "ERR_TEST_BENCH_NOT_FOUND",
    "loaner_units": "ERR_LOANER_UNIT_NOT_FOUND",
    "intake_shipments": "ERR_SHIPMENT_NOT_FOUND",
    "equipment_units": "ERR_UNIT_NOT_FOUND",
    "shell_tests": "ERR_SHELL_TEST_NOT_FOUND",
    "repair_orders": "ERR_REPAIR_ORDER_NOT_FOUND",
    "certification_labels": "ERR_LABEL_NOT_FOUND",
    "destruction_records": "ERR_DESTRUCTION_RECORD_NOT_FOUND",
    "loaner_assignments": "ERR_LOANER_ASSIGNMENT_NOT_FOUND",
}


def fetch(collection, row_id):
    """Resolve a reference or raise the collection's specific not-found error."""
    if not isinstance(row_id, str):
        raise ApiError(NOT_FOUND[collection])
    record = getattr(db.db, collection).get(row_id)
    if record is None:
        raise ApiError(NOT_FOUND[collection])
    return record


def account(row_id):
    return fetch("customer_accounts", row_id)


def model(row_id):
    return fetch("model_specs", row_id)


def part(row_id):
    return fetch("approved_parts", row_id)


def bench(row_id):
    return fetch("test_benches", row_id)


def loaner(row_id):
    return fetch("loaner_units", row_id)


def shipment(row_id):
    return fetch("intake_shipments", row_id)


def unit(row_id):
    return fetch("equipment_units", row_id)


def shell_test(row_id):
    return fetch("shell_tests", row_id)


def repair_order(row_id):
    return fetch("repair_orders", row_id)


def label(row_id):
    return fetch("certification_labels", row_id)


def destruction(row_id):
    return fetch("destruction_records", row_id)


def assignment(row_id):
    return fetch("loaner_assignments", row_id)


def listing(collection, serializer, filters=None):
    """created_at-ascending page of a collection under equality filters."""
    rows = list(getattr(db.db, collection).values())
    for field, value in (filters or {}).items():
        if value is not None:
            rows = [row for row in rows if row.get(field) == value]
    rows = db.ordered(rows)
    page, meta = paginate(rows)
    return ok_list([serializer(row) for row in page], meta)


def single(record, serializer, status=200):
    return ok(serializer(record), status)
