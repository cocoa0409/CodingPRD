"""Path-id resolution, foreign-key resolution and the commit step."""
from flask import request

import derive
import store
from errors import ApiError

_LOOKUPS = (
    ("affiliates", store.affiliates, "ERR_AFFILIATE_NOT_FOUND"),
    ("agreements", store.agreements, "ERR_AGREEMENT_NOT_FOUND"),
    ("reviews", store.reviews, "ERR_FACILITY_REVIEW_NOT_FOUND"),
    ("staff_members", store.staff_members, "ERR_STAFF_MEMBER_NOT_FOUND"),
    ("allocations", store.allocations, "ERR_STAFF_ALLOCATION_NOT_FOUND"),
    ("players", store.players, "ERR_PLAYER_NOT_FOUND"),
    ("assignments", store.assignments, "ERR_ASSIGNMENT_NOT_FOUND"),
    ("plans", store.plans, "ERR_DEVELOPMENT_PLAN_NOT_FOUND"),
    ("clearances", store.clearances, "ERR_MEDICAL_CLEARANCE_NOT_FOUND"),
    ("pools", store.pools, "ERR_SIGNING_POOL_NOT_FOUND"),
    ("signings", store.signings, "ERR_SIGNING_NOT_FOUND"),
    ("reports", store.reports, "ERR_TRANSACTION_REPORT_NOT_FOUND"),
)

_BY_NAME = {name: (coll, err) for name, coll, err in _LOOKUPS}


def find(kind, record_id):
    """Return the record or None."""
    coll, _ = _BY_NAME[kind]
    if not isinstance(record_id, str):
        return None
    return coll.get(record_id)


def need(kind, record_id):
    """Resolve a path or body id, raising the collection's not-found error."""
    coll, error_id = _BY_NAME[kind]
    if not isinstance(record_id, str):
        raise ApiError(error_id)
    record = coll.get(record_id)
    if record is None:
        raise ApiError(error_id)
    return record


def commit():
    """Reconcile every derived field, then apply audit-field bumps."""
    derive.reconcile_all()
    store.finalize_request()


def filter_arg(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def bool_arg(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    return None


def apply_filters(rows, spec):
    """spec: sequence of (query-parameter name, record field name)."""
    for arg_name, field in spec:
        wanted = filter_arg(arg_name)
        if wanted is None:
            continue
        rows = [r for r in rows if r.get(field) == wanted]
    return rows
