"""Shared helpers for the route blueprints."""

from flask import request

import db
from errors import fail

# The generic 404 for every entity whose path segment has no dedicated code.
NOT_FOUND = {
    "app_products": "ERR_APP_PRODUCT_NOT_FOUND",
    "consumers": "ERR_CONSUMER_NOT_FOUND",
    "vendors": "ERR_VENDOR_NOT_FOUND",
    "data_elements": "ERR_DATA_ELEMENT_NOT_FOUND",
    "processing_purposes": "ERR_PURPOSE_NOT_FOUND",
}

TERMINAL_STATES = {
    "applicability_assessments": ("SUPERSEDED",),
    "data_elements": (),
    "element_purpose_mappings": ("RETIRED",),
    "consent_records": ("SUPERSEDED",),
    "privacy_policy_versions": ("SUPERSEDED",),
    "consumer_requests": ("FULFILLED", "DENIED"),
    "deletion_tasks": ("CONFIRMED",),
    "vendors": ("TERMINATED",),
    "geofence_campaigns": ("ENDED",),
    "breach_incidents": ("NOTIFIED", "NOT_REPORTABLE"),
    "security_risk_assessments": ("FINALIZED",),
}


def load(table, row_id):
    """Resolve a path or body identifier, raising the per-entity 404."""
    row = db.get(table, row_id)
    if row is None:
        fail(NOT_FOUND.get(table, "ERR_RESOURCE_NOT_FOUND"))
    return row


def check_state(row, table, allowed, specific=None, field="state"):
    """Precedence check 8: from-state admissibility."""
    current = row.get(field)
    if current in allowed:
        return
    if specific:
        fail(specific)
    if current in TERMINAL_STATES.get(table, ()):
        fail("ERR_ALREADY_TERMINAL")
    fail("ERR_INVALID_STATE")


def filter_rows(table, spec):
    """Apply the endpoint's declared equality filters from the query string."""
    rows = db.rows_of(table)
    for param, field in spec.items():
        value = request.args.get(param)
        if value is None:
            continue
        rows = [r for r in rows if str(r.get(field)) == value]
    return rows


def consumer_scope(role, user_id, consumer_id):
    """Precedence check 7: a Consumer may act only on its own resources."""
    if role == "Consumer" and user_id != consumer_id:
        fail("ERR_CONSUMER_SCOPE_VIOLATION")
