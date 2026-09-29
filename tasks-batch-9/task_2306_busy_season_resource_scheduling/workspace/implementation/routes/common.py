"""Helpers shared by the route modules."""

from datetime import datetime

from flask import request

import db
import response
import validation
from errors import ApiError

# Sentinel for a filter value that cannot possibly match any stored row.
INVALID = object()


def page(rows, serializer):
    """Apply ladder stage 7 and emit the paginated list envelope."""
    limit, offset = validation.pagination()
    total = len(rows)
    window = rows[offset : offset + limit]
    return response.list_response([serializer(row) for row in window], limit, offset, total)


def empty_page():
    limit, offset = validation.pagination()
    return response.list_response([], limit, offset, 0)


def q(name):
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def q_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    low = raw.strip().lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    return INVALID


def q_date(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except ValueError:
        return INVALID


def has_invalid(*values):
    return any(value is INVALID for value in values)


def require_unblocked(engagement):
    """Ladder stage 12."""
    if engagement["status"] not in ("SETUP", "SCHEDULED", "IN_FIELDWORK"):
        raise ApiError(
            "ERR_ENGAGEMENT_BLOCKED",
            "The owning engagement is %s and accepts no staffing write." % engagement["status"],
        )
    return engagement


def engagement_of(phase):
    return db.engagements.get(phase["engagement_id"])


def phase_of(assignment):
    return db.phases.get(assignment["engagement_phase_id"])
