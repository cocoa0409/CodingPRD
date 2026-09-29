"""Helpers shared by every route module."""
from flask import request

from db import db, sort_key
from errors import ApiError

TERMINAL_STATES = {
    "LicenseRegistration": ("SURRENDERED", "REVOKED"),
    "SponsorshipTransfer": ("RELINQUISHED", "SUPERSEDED"),
    "CompensationPlan": ("REJECTED", "SUPERSEDED"),
    "LoanApplication": ("WITHDRAWN",),
    "PricingException": ("APPROVED", "DENIED", "WITHDRAWN"),
    "CompensationRecord": ("CLAWED_BACK",),
    "Advertisement": ("WITHDRAWN",),
    "ExaminationInquiry": ("CLOSED",),
    "UnlicensedActivityInvestigation": ("UNSUBSTANTIATED", "REMEDIATED"),
}


def get_or_404(collection, row_id):
    """Priority 5: every id in the path resolves, checked left to right."""
    row = collection.get(row_id)
    if row is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    return row


def get_referenced(collection, row_id):
    """Priority 6: a foreign key in the request body resolves."""
    row = collection.get(row_id)
    if row is None:
        raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND")
    return row


def gate(entity, row, allowed, field="status"):
    """Priorities 11 and 12. A row already parked in one of its machine's
    terminal states reports ERR_ALREADY_TERMINAL; any other unmatched source
    state reports ERR_INVALID_STATE_TRANSITION."""
    current = row[field]
    if current in TERMINAL_STATES.get(entity, ()):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if current not in allowed:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")


def invalid_transition():
    return ApiError("ERR_INVALID_STATE_TRANSITION")


def listing(collection, predicate=None):
    rows = [r for r in collection.values() if predicate is None or predicate(r)]
    rows.sort(key=sort_key)
    return rows


def filters(*names):
    """Read the declared query filters that are actually present."""
    out = {}
    for name in names:
        value = request.args.get(name)
        if value is not None:
            out[name] = value
    return out


def matches(row, active_filters, int_fields=()):
    for name, wanted in active_filters.items():
        actual = row.get(name)
        if name in int_fields:
            try:
                wanted_value = int(wanted)
            except (TypeError, ValueError):
                return False
            if actual != wanted_value:
                return False
        else:
            if actual != wanted:
                return False
    return True


def originator_of_loan(loan_id):
    loan = db.loan_applications.get(loan_id)
    return None if loan is None else loan["originator_id"]
