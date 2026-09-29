"""Shared lookup and filter helpers for the route modules."""

from flask import request

from db import db
from errors import ApiError
from validation import paginate, pagination


def _get(collection, row_id, error_id):
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id, "No such resource: %s" % row_id)
    return row


def get_facility(facility_id):
    return _get(db.facilities, facility_id, "ERR_FACILITY_NOT_FOUND")


def get_advance(advance_id):
    return _get(db.advances, advance_id, "ERR_ADVANCE_NOT_FOUND")


def get_investor(investor_id):
    return _get(db.investors, investor_id, "ERR_INVESTOR_NOT_FOUND")


def get_custodian(custodian_id):
    return _get(db.custodians, custodian_id, "ERR_CUSTODIAN_NOT_FOUND")


def get_commitment(commitment_id):
    return _get(db.commitments, commitment_id, "ERR_COMMITMENT_NOT_FOUND")


def get_margin_call(call_id):
    return _get(db.margin_calls, call_id, "ERR_MARGIN_CALL_NOT_FOUND")


def get_wire(wire_id):
    return _get(db.wires, wire_id, "ERR_WIRE_INSTRUCTION_NOT_FOUND")


def get_receipt(receipt_id):
    return _get(db.receipts, receipt_id, "ERR_RECEIPT_NOT_FOUND")


def get_covenant_test(test_id):
    return _get(db.covenant_tests, test_id, "ERR_COVENANT_TEST_NOT_FOUND")


def get_demand(demand_id):
    return _get(db.demands, demand_id, "ERR_REPURCHASE_DEMAND_NOT_FOUND")


def advance_facility(advance):
    return db.facilities[advance["facility_id"]]


def filter_by(rows, field, param=None):
    value = request.args.get(param or field)
    if value is None or value == "":
        return rows
    return [r for r in rows if r.get(field) == value]


def list_response(rows, serializer):
    from response import ok_list
    limit, offset = pagination()
    page, total = paginate(rows, limit, offset)
    return ok_list([serializer(row) for row in page], limit, offset, total)
