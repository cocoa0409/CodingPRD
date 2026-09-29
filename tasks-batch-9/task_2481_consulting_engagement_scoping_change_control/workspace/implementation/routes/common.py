"""Helpers shared by every route module."""

from flask import g

from db import db, rows
from errors import NOT_FOUND_ID, fail
from middleware import ROLE_CLIENT
from response import ok_list
from validators import pagination

TABLE_FAMILY = {
    "clients": "client",
    "consultants": "consultant",
    "opportunities": "opportunity",
    "deliverables": "deliverable",
    "sows": "sow",
    "engagements": "engagement",
    "change_requests": "change_request",
    "time_entries": "time_entry",
    "quality_reviews": "quality_review",
    "risk_escalations": "risk_escalation",
    "satisfaction_assessments": "satisfaction_assessment",
}


def lookup(table, row_id):
    """Fetch without raising, so authorisation may run before the 404 is emitted."""
    if row_id is None:
        return None
    return getattr(db, table).get(row_id)


def need(row, table):
    if row is None:
        fail(NOT_FOUND_ID[TABLE_FAMILY[table]])
    return row


def fetch(table, row_id):
    return need(lookup(table, row_id), table)


def fk(table, row_id):
    """Resolve a body foreign key; 404 with the referenced family's code."""
    if row_id is None:
        return None
    return need(lookup(table, row_id), table)


def paged(items, serializer):
    limit, offset = pagination()
    total = len(items)
    window = items[offset : offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)


def filtered(table, predicate=None):
    out = rows(table)
    if predicate is not None:
        out = [r for r in out if predicate(r)]
    return out


def acting_client_id():
    return g.user_id if g.role == ROLE_CLIENT else None
