"""Helpers shared by the route blueprints."""

import errors
import response
import validation
from db import db, values
from errors import fail

PREFIX = "/nac"


def owned_contract(caller, contract):
    """Entity-backed ownership for OperatorBuyer (PRD 2.1)."""
    if caller.role == "OperatorBuyer" and caller.user_id != contract["operator_id"]:
        fail(errors.ERR_UNAUTHORIZED)
    return contract


def contract_of(entity):
    return db.contracts[entity["contract_id"]]


def require_contract_active(contract, allow_draft=False):
    """Priority 6 of the rejection ladder."""
    allowed = ("DRAFT", "ACTIVE") if allow_draft else ("ACTIVE",)
    if contract["status"] not in allowed:
        fail(errors.ERR_CONTRACT_NOT_ACTIVE)


def require_state(record, allowed, error_id):
    """Priority 5 of the rejection ladder."""
    if record["status"] not in allowed:
        fail(error_id)


def unique_or_reject(collection, field, value, scope_field=None, scope_value=None):
    for row in collection.values():
        if row.get(field) != value:
            continue
        if scope_field is not None and row.get(scope_field) != scope_value:
            continue
        fail(errors.ERR_INVALID_REQUEST, "%s must be unique." % field)


def listing(collection, spec):
    """Apply conjunctive equality filters, then paginate. `spec` is a sequence of
    (query_param, record_field, enum_values_or_None) triples."""
    rows = values(collection)
    for param, field, enum_values in spec:
        if enum_values is not None:
            wanted = validation.query_enum(param, enum_values)
        else:
            wanted = validation.query_value(param)
        if wanted is None:
            continue
        rows = [row for row in rows if row.get(field) == wanted]
    window, limit, offset, total = validation.paginate(rows)
    return response.collection([response.serialize(row) for row in window],
                               limit, offset, total)


def require_order(*intervals):
    """Upper bound strictly after lower bound (PRD 2.5)."""
    for lower, upper, name in intervals:
        if upper <= lower:
            fail(errors.ERR_INVALID_REQUEST,
                 "%s must be strictly after its lower bound." % name)
