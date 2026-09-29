"""Shared route helpers: path resolution, body foreign keys and list filters."""

from flask import request

import db
from errors import ApiError
from services import calc, derive

NOT_FOUND = {
    "licensee": "ERR_LICENSEE_NOT_FOUND",
    "bond": "ERR_BOND_NOT_FOUND",
    "terminal": "ERR_TERMINAL_NOT_FOUND",
    "certificate": "ERR_CERTIFICATE_NOT_FOUND",
    "rack_removal": "ERR_RACK_REMOVAL_NOT_FOUND",
    "return": "ERR_RETURN_NOT_FOUND",
    "schedule": "ERR_SCHEDULE_NOT_FOUND",
    "schedule_line": "ERR_SCHEDULE_LINE_NOT_FOUND",
    "cross_match_run": "ERR_CROSS_MATCH_RUN_NOT_FOUND",
    "discrepancy": "ERR_DISCREPANCY_NOT_FOUND",
    "refund_claim": "ERR_REFUND_CLAIM_NOT_FOUND",
    "inspection": "ERR_INSPECTION_NOT_FOUND",
    "audit_case": "ERR_AUDIT_CASE_NOT_FOUND",
}

STORES = {
    "licensee": db.licensees,
    "bond": db.bonds,
    "terminal": db.terminals,
    "certificate": db.certificates,
    "rack_removal": db.rack_removals,
    "return": db.returns,
    "schedule": db.schedules,
    "schedule_line": db.schedule_lines,
    "cross_match_run": db.cross_match_runs,
    "discrepancy": db.discrepancies,
    "refund_claim": db.refund_claims,
    "inspection": db.inspections,
    "audit_case": db.audit_cases,
}


def find(kind, row_id):
    """Resolve a path identifier or raise that resource's 404."""
    row = STORES[kind].get(row_id)
    if row is None:
        raise ApiError(NOT_FOUND[kind])
    return row


def maybe(kind, row_id):
    return STORES[kind].get(row_id)


def body_licensee(row_id):
    """Resolve a body foreign key naming a licensee (band 7)."""
    row = db.licensees.get(row_id)
    if row is None:
        raise ApiError("ERR_LICENSEE_NOT_FOUND")
    return row


def body_ref(kind, row_id):
    row = STORES[kind].get(row_id)
    if row is None:
        raise ApiError(NOT_FOUND[kind])
    return row


# --------------------------------------------------------------------------
# List filters.  Unknown query parameters are ignored.
# --------------------------------------------------------------------------
def eq_filter(rows, param, field=None, transform=None):
    value = request.args.get(param)
    if value is None:
        return rows
    field = field or param
    if transform is not None:
        value = transform(value)
    return [r for r in rows if r.get(field) == value]


def filter_by(rows, mapping):
    for param, field in mapping.items():
        rows = eq_filter(rows, param, field)
    return rows


def filter_removal_month(rows):
    value = request.args.get("removal_month")
    if value is None:
        return rows
    return [r for r in rows
            if r["removal_date"].strftime("%Y-%m") == value]


def agent_narrow(rows, owner_fn, user_id, role):
    """List endpoints are silently narrowed for a LicenseeAgent (PRD 2.1)."""
    if role != "LicenseeAgent":
        return rows
    return [r for r in rows if owner_fn(r) == user_id]


def cents_field(data, field, minimum=None):
    """A monetary integer field."""
    from shape import req_int
    return req_int(data, field, minimum=minimum)


def gallons_sum(lines):
    total = calc.ZERO
    for line in lines:
        total += line["gallons"]
    return calc.g2(total)


def product_schedule_gallons(return_id, schedule_code, product_code):
    """The exact two-decimal sum of line gallons on one schedule block."""
    total = calc.ZERO
    for schedule in derive.return_schedules(return_id):
        if (schedule["schedule_code"] == schedule_code
                and schedule["product_code"] == product_code):
            total += derive.schedule_gallons_sum(schedule["id"])
    return calc.g2(total)


# --------------------------------------------------------------------------
# Ladder-ordered path resolution.
#
# Licensee scope is band 3 and path existence is band 6, with request shape
# (band 4) and pagination (band 5) in between.  Callers therefore peek at the
# addressed row, scope-check it when it exists, validate the body, and only
# then insist that it exists.
# --------------------------------------------------------------------------
def peek(kind, row_id, user_id, role, owner_fn=None):
    import middleware
    row = STORES[kind].get(row_id)
    if row is not None:
        owner = owner_fn(row) if owner_fn else row["id"]
        middleware.scope_guard(user_id, role, owner)
    return row


def ensure(kind, row):
    if row is None:
        raise ApiError(NOT_FOUND[kind])
    return row


def owner_of_return(row):
    return row["licensee_id"]


def owner_of_schedule(row):
    return derive.schedule_owner_licensee_id(row)


def owner_of_line(row):
    return derive.line_owner_licensee_id(row)


def owner_of_discrepancy(row):
    return row["distributor_licensee_id"]
