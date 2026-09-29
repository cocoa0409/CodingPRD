"""Entity lookups (each raising its own not-found error) and list windowing."""

from db import db, ordered
from errors import ApiError
from response import list_response


def _get(table, key, error_id):
    if not isinstance(key, str):
        raise ApiError(error_id)
    row = table.get(key)
    if row is None:
        raise ApiError(error_id)
    return row


def facility(key):
    return _get(db.facilities, key, "ERR_FACILITY_NOT_FOUND")


def department(key):
    return _get(db.departments, key, "ERR_DEPARTMENT_NOT_FOUND")


def cycle(key):
    return _get(db.cycles, key, "ERR_CYCLE_NOT_FOUND")


def allocation(key):
    return _get(db.allocations, key, "ERR_ALLOCATION_NOT_FOUND")


def asset(key):
    return _get(db.assets, key, "ERR_ASSET_NOT_FOUND")


def request_row(key):
    return _get(db.requests, key, "ERR_REQUEST_NOT_FOUND")


def member(key):
    return _get(db.members, key, "ERR_MEMBER_NOT_FOUND")


def contract(key):
    return _get(db.contracts, key, "ERR_GPO_CONTRACT_NOT_FOUND")


def quote(key):
    return _get(db.quotes, key, "ERR_QUOTE_NOT_FOUND")


def project(key):
    return _get(db.projects, key, "ERR_PROJECT_NOT_FOUND")


def audit(key):
    return _get(db.audits, key, "ERR_AUDIT_NOT_FOUND")


# ------------------------------------------------------------------ helpers

def request_facility_id(req):
    dept = db.departments.get(req["department_id"])
    return dept["facility_id"] if dept else None


def find_allocation(cycle_id, facility_id, postures=("ACTIVE", "EXHAUSTED")):
    for row in ordered(db.allocations.values()):
        if (row["cycle_id"] == cycle_id and row["facility_id"] == facility_id
                and row["posture"] in postures):
            return row
    return None


def accepted_quote(request_id):
    for row in ordered(db.quotes.values()):
        if row["request_id"] == request_id and row["status"] == "ACCEPTED":
            return row
    return None


def filtered(rows, filters):
    """Equality filters; the sentinel "__nomatch__" simply matches nothing."""
    out = []
    for row in rows:
        keep = True
        for field, value in filters:
            if value is None:
                continue
            if row.get(field) != value:
                keep = False
                break
        if keep:
            out.append(row)
    return out


def paginate(rows, limit, offset, projector):
    rows = ordered(rows)
    total = len(rows)
    window = rows[offset:offset + limit]
    return list_response([projector(row) for row in window], limit, offset, total)
