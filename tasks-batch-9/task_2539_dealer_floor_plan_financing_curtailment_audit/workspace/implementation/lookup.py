"""Band 4 existence resolution: path parameters left to right, then body
references in their declared input order."""

import db
from errors import ApiError

_TABLES = {
    "dealers": "ERR_DEALER_NOT_FOUND",
    "credit_lines": "ERR_CREDIT_LINE_NOT_FOUND",
    "inventory_units": "ERR_UNIT_NOT_FOUND",
    "funding_advances": "ERR_ADVANCE_NOT_FOUND",
    "curtailment_obligations": "ERR_OBLIGATION_NOT_FOUND",
    "aging_exceptions": "ERR_EXCEPTION_NOT_FOUND",
    "audits": "ERR_AUDIT_NOT_FOUND",
    "incidents": "ERR_INCIDENT_NOT_FOUND",
    "remedy_actions": "ERR_REMEDY_NOT_FOUND",
    "remittances": "ERR_REMITTANCE_NOT_FOUND",
}


def _find(table, record_id):
    record = db.get(table, record_id)
    if record is None:
        raise ApiError(_TABLES[table])
    return record


def dealer(record_id):
    return _find("dealers", record_id)


def credit_line(record_id):
    return _find("credit_lines", record_id)


def unit(record_id):
    return _find("inventory_units", record_id)


def advance(record_id):
    return _find("funding_advances", record_id)


def obligation(record_id):
    return _find("curtailment_obligations", record_id)


def exception_request(record_id):
    return _find("aging_exceptions", record_id)


def audit(record_id):
    return _find("audits", record_id)


def incident(record_id):
    return _find("incidents", record_id)


def remedy(record_id):
    return _find("remedy_actions", record_id)


def remittance(record_id):
    return _find("remittances", record_id)
