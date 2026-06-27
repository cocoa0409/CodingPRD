"""Shared resource lookups and ownership checks for route handlers.

Existence is validated left-to-right; the first unresolved id -> ERR_NOT_FOUND
(PRD §2.9). Ownership (Customer acting on a Customer-backed resource) ->
ERR_NOT_RESOURCE_OWNER (PRD §2.1, validation priority 3).
"""

from flask import g

import errors
from db import db


def get_or_404(table, rid):
    rec = table.get(rid)
    if rec is None:
        raise errors.not_found()
    return rec


def require_owner(customer_id):
    """When acting as Customer, X-User-ID must equal the resource's customer_id."""
    if g.user_role == "Customer" and g.user_id != customer_id:
        raise errors.not_resource_owner()
