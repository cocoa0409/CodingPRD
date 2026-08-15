"""Shared helpers for route handlers: serialization, pagination, nested
path resolution (left-to-right per PRD 2.7), and Customer ownership checks.
"""

from __future__ import annotations

from flask import request

import db
from errors import ApiError, HTTP_STATUS
from errors import (
    ERR_PROJECT_NOT_FOUND,
    ERR_LAYOUT_NOT_FOUND,
    ERR_ITEM_NOT_FOUND,
    ERR_QUOTE_NOT_FOUND,
    ERR_FILING_NOT_FOUND,
    ERR_JOB_NOT_FOUND,
    ERR_SESSION_NOT_FOUND,
    ERR_AGENCY_NOT_FOUND,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_FAB_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INSUFFICIENT_PERMISSIONS,
)
from response import success_list

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def serialize(entity: dict) -> dict:
    """Strip internal bookkeeping keys (anything prefixed with '_')."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def not_found(error_id: str, what: str) -> None:
    raise ApiError(error_id, HTTP_STATUS[error_id], f"{what} not found")


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3): limit/offset query params, defaults 10/0, bounds
# 1..100 on limit, 0 floor on offset; results sorted by created_at ascending.
# ---------------------------------------------------------------------------

def _parse_page_int(raw, name):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be an integer")


def paginate(records: list[dict]):
    """records: pre-filtered dicts with _seq/created_at. Returns a Flask
    response tuple with the list envelope."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = PAGINATION_DEFAULT_LIMIT if limit_raw is None else _parse_page_int(limit_raw, "limit")
    offset = PAGINATION_DEFAULT_OFFSET if offset_raw is None else _parse_page_int(offset_raw, "offset")
    limit = max(PAGINATION_MIN_LIMIT, min(PAGINATION_MAX_LIMIT, limit))
    offset = max(PAGINATION_DEFAULT_OFFSET, offset)
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return success_list([serialize(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Path resolution (PRD 2.7): left to right; scoped children must belong to
# the resolved parent or the child's own not-found error is returned.
# ---------------------------------------------------------------------------

def resolve_project(project_id: str) -> dict:
    project = db.projects.get(project_id)
    if project is None:
        not_found(ERR_PROJECT_NOT_FOUND, "Project")
    return project


def resolve_customer(customer_id: str) -> dict:
    customer = db.customers.get(customer_id)
    if customer is None:
        not_found(ERR_CUSTOMER_NOT_FOUND, "Customer")
    return customer


def resolve_layout(project: dict, layout_id: str) -> dict:
    layout = db.layouts.get(layout_id)
    if layout is None or layout["project_id"] != project["id"]:
        not_found(ERR_LAYOUT_NOT_FOUND, "KitchenLayout")
    return layout


def resolve_layout_any(layout_id: str) -> dict:
    layout = db.layouts.get(layout_id)
    if layout is None:
        not_found(ERR_LAYOUT_NOT_FOUND, "KitchenLayout")
    return layout


def resolve_item(project: dict, item_id: str) -> dict:
    item = db.items.get(item_id)
    if item is None or item["project_id"] != project["id"]:
        not_found(ERR_ITEM_NOT_FOUND, "EquipmentItem")
    return item


def resolve_item_any(item_id: str) -> dict:
    item = db.items.get(item_id)
    if item is None:
        not_found(ERR_ITEM_NOT_FOUND, "EquipmentItem")
    return item


def resolve_quote(project: dict, quote_id: str) -> dict:
    quote = db.quotes.get(quote_id)
    if quote is None or quote["project_id"] != project["id"]:
        not_found(ERR_QUOTE_NOT_FOUND, "Quote")
    return quote


def resolve_quote_any(quote_id: str) -> dict:
    quote = db.quotes.get(quote_id)
    if quote is None:
        not_found(ERR_QUOTE_NOT_FOUND, "Quote")
    return quote


def resolve_fab(project: dict, fab_id: str) -> dict:
    fab = db.fab_orders.get(fab_id)
    if fab is None or fab["project_id"] != project["id"]:
        not_found(ERR_FAB_NOT_FOUND, "FabricationOrder")
    return fab


def resolve_fab_any(fab_id: str) -> dict:
    fab = db.fab_orders.get(fab_id)
    if fab is None:
        not_found(ERR_FAB_NOT_FOUND, "FabricationOrder")
    return fab


def resolve_filing(project: dict, filing_id: str) -> dict:
    filing = db.filings.get(filing_id)
    if filing is None or filing["project_id"] != project["id"]:
        not_found(ERR_FILING_NOT_FOUND, "PermitFiling")
    return filing


def resolve_filing_any(filing_id: str) -> dict:
    filing = db.filings.get(filing_id)
    if filing is None:
        not_found(ERR_FILING_NOT_FOUND, "PermitFiling")
    return filing


def resolve_job(project: dict, job_id: str) -> dict:
    job = db.jobs.get(job_id)
    if job is None or job["project_id"] != project["id"]:
        not_found(ERR_JOB_NOT_FOUND, "DeliveryJob")
    return job


def resolve_job_any(job_id: str) -> dict:
    job = db.jobs.get(job_id)
    if job is None:
        not_found(ERR_JOB_NOT_FOUND, "DeliveryJob")
    return job


def resolve_session(project: dict, session_id: str) -> dict:
    session = db.sessions.get(session_id)
    if session is None or session["project_id"] != project["id"]:
        not_found(ERR_SESSION_NOT_FOUND, "StartupSession")
    return session


def resolve_session_any(session_id: str) -> dict:
    session = db.sessions.get(session_id)
    if session is None:
        not_found(ERR_SESSION_NOT_FOUND, "StartupSession")
    return session


def resolve_agency(agency_id: str) -> dict:
    agency = db.agencies.get(agency_id)
    if agency is None:
        not_found(ERR_AGENCY_NOT_FOUND, "ServiceAgency")
    return agency


def resolve_assignment(project: dict, assignment_id: str) -> dict:
    assignment = db.assignments.get(assignment_id)
    if assignment is None or assignment["project_id"] != project["id"]:
        not_found(ERR_ASSIGNMENT_NOT_FOUND, "ServiceAssignment")
    return assignment


def resolve_assignment_any(assignment_id: str) -> dict:
    assignment = db.assignments.get(assignment_id)
    if assignment is None:
        not_found(ERR_ASSIGNMENT_NOT_FOUND, "ServiceAssignment")
    return assignment


def resolve_punch(project: dict, item_id: str) -> dict:
    punch = db.punch_items.get(item_id)
    if punch is None or punch["project_id"] != project["id"]:
        not_found(ERR_ITEM_NOT_FOUND, "PunchListItem")
    return punch


def resolve_punch_any(item_id: str) -> dict:
    punch = db.punch_items.get(item_id)
    if punch is None:
        not_found(ERR_ITEM_NOT_FOUND, "PunchListItem")
    return punch


# ---------------------------------------------------------------------------
# Customer ownership (PRD 2.1): when the caller role is Customer, X-User-ID
# is the acting Customer entity id and must match the owning customer FK.
# ---------------------------------------------------------------------------

def check_project_ownership(user_id: str, role: str, project: dict) -> None:
    if role == "Customer" and project["customer_id"] != user_id:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            HTTP_STATUS[ERR_INSUFFICIENT_PERMISSIONS],
            "Customer may access only its own resources",
        )
