"""Shared route plumbing: filtered listings, scope guards and state guards."""

from flask import g, request

from core import (
    ROLE_INVESTOR, ROLE_FUND_MANAGER, fail, list_response, object_response,
    rows,
)
from serialize import dump, dump_all


def listing(collection, filters=(), page=None, extra=None):
    """Default ordering is creation order; filters are exact-match equality."""
    wanted = []
    for param, field in filters:
        value = request.args.get(param)
        if value is not None:
            wanted.append((field, value))

    def keep(row):
        if extra is not None and not extra(row):
            return False
        for field, value in wanted:
            current = row.get(field)
            if current is None or str(current) != value:
                return False
        return True

    return list_response(dump_all(rows(collection, keep)), page)


def one(row, status=200):
    return object_response(dump(row), status)


# ---------------------------------------------------------------------------
# Scope guards (validation priorities 8 and 9)
# ---------------------------------------------------------------------------

def investor_scope(investor_id):
    if g.role == ROLE_INVESTOR and g.user_id != investor_id:
        fail("ERR_INVESTOR_SCOPE_VIOLATION",
             "Investor may only act within its own records")


def manager_scope(fund):
    if g.role == ROLE_FUND_MANAGER and g.user_id != fund["manager_user_id"]:
        fail("ERR_FUND_MANAGER_MISMATCH",
             "Caller does not manage fund '%s'" % fund["id"])


def segregation(measured_by):
    if measured_by is not None and g.user_id == measured_by:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The certifier may not be the operator that measured")


# ---------------------------------------------------------------------------
# State guards (validation priorities 13 and 14)
# ---------------------------------------------------------------------------

def guard_state(current, allowed, terminal):
    """Priority 14 wins whenever the resource already sits in a terminal state;
    priority 13 covers every other undeclared transition."""
    if current in terminal:
        fail("ERR_ALREADY_TERMINAL",
             "Resource is already in terminal state '%s'" % current)
    if current not in allowed:
        fail("ERR_INVALID_STATE_TRANSITION",
             "Transition out of '%s' is not declared" % current)


def guard_transition(current, allowed):
    """Priority 13 only -- used where priority 14 is explicitly carved out."""
    if current not in allowed:
        fail("ERR_INVALID_STATE_TRANSITION",
             "Transition out of '%s' is not declared" % current)
