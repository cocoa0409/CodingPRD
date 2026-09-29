"""Helpers shared by every route module."""

from db import DB, rows_sorted, serialize
from errors import ApiError
from middleware import apply_filters, filters, pagination
from response import list_response, object_response
from services import derive

NOT_FOUND = {
    "permit_terms": "ERR_PERMIT_TERM_NOT_FOUND",
    "control_measures": "ERR_CONTROL_MEASURE_NOT_FOUND",
    "outfalls": "ERR_OUTFALL_NOT_FOUND",
    "observations": "ERR_OBSERVATION_NOT_FOUND",
    "cases": "ERR_CASE_NOT_FOUND",
    "sites": "ERR_CONSTRUCTION_SITE_NOT_FOUND",
    "facilities": "ERR_FACILITY_NOT_FOUND",
    "inspections": "ERR_INSPECTION_NOT_FOUND",
    "enforcement_actions": "ERR_ENFORCEMENT_ACTION_NOT_FOUND",
    "accounts": "ERR_ACCOUNT_NOT_FOUND",
    "credit_applications": "ERR_CREDIT_APPLICATION_NOT_FOUND",
    "annual_reports": "ERR_ANNUAL_REPORT_NOT_FOUND",
}


def find(collection, row_id):
    """Resolve an identifier or raise the 404 belonging to the entity kind."""
    rows = getattr(DB, collection)
    row = rows.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(NOT_FOUND[collection])
    return row


def one(row, status=200):
    return object_response(serialize(row), status)


def paged(rows, limit, offset):
    ordered = rows_sorted(rows)
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return list_response([serialize(r) for r in page], limit, offset, total)


def listing(spec, resolve):
    """Validate the query string (400) before resolving any path id (404)."""
    limit, offset = pagination()
    active = filters(spec)
    rows = resolve()
    return paged(apply_filters(rows, active), limit, offset)


def require_active(term):
    if term is None or term.get("status") != "ACTIVE":
        raise ApiError("ERR_PERMIT_TERM_NOT_ACTIVE")
    return term


def snapshot(term):
    return derive.snapshot(term)


def settle(term, before=None, event_instant=None):
    """Recompute the whole term and, when asked, run report invalidation."""
    if term is None:
        return
    derive.recompute_world(term)
    if before is not None and event_instant is not None:
        derive.invalidate_reports(term, before, event_instant)
