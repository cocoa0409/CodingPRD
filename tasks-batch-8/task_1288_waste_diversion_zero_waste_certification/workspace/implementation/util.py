"""Shared helpers: pagination, filtering, sorting, enums."""

import re

from flask import request

from errors import ApiError, ERR_INVALID_REQUEST

MATERIAL_STREAMS = [
    "MIXED_RECYCLABLES",
    "CARDBOARD",
    "COMPOST_ORGANICS",
    "MIXED_SOLID_WASTE",
    "E_WASTE",
]
DISPOSAL_ROUTES = ["RECYCLING", "COMPOSTING", "REUSE", "LANDFILL", "ENERGY_RECOVERY"]
DIVERTED_ROUTES = {"RECYCLING", "COMPOSTING", "REUSE"}
VENDOR_TYPES = ["HAULER", "RECYCLER", "PROCESSOR"]
VENDOR_STATUSES = ["ACTIVE", "SUSPENDED"]
CONTRACT_STATUSES = ["DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED", "EXPIRED"]
TICKET_STATUSES = ["PENDING", "VALIDATED", "REJECTED", "VOIDED"]
EVENT_STATUSES = ["OPEN", "TRAINING_ASSIGNED", "TRAINING_COMPLETED",
                  "VERIFIED_CLOSED", "DISMISSED"]
GOAL_METRICS = ["DIVERSION_RATE", "COST_AVOIDANCE", "CONTAMINATION_EVENTS"]
GOAL_STATUSES = ["ACTIVE", "ACHIEVED", "MISSED", "CANCELLED"]
PERIOD_STATUSES = ["OPEN", "CLOSED"]
LEVELS = ["BRONZE", "SILVER", "GOLD", "ZERO_WASTE"]
APPLICATION_STATUSES = ["DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED",
                        "REJECTED", "WITHDRAWN", "SUPERSEDED", "LAPSED"]

_INT_RE = re.compile(r"^\d+$")


def parse_pagination():
    """limit (default 10, min 1, max 100) and offset (default 0)."""
    limit, offset = 10, 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        if not _INT_RE.match(raw_limit):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        limit = int(raw_limit)
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "limit must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        if not _INT_RE.match(raw_offset):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        offset = int(raw_offset)
    return limit, offset


def sort_items(items):
    """Default list sort: created_at ascending (insertion order tie-break)."""
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


def paginate(items):
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def apply_filters(items, specs):
    """Apply query filters. specs: list of (query_param, record_field, enum|None)."""
    out = list(items)
    for param, field, enum in specs:
        raw = request.args.get(param)
        if raw is None:
            continue
        if enum is not None and raw not in enum:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           f"Invalid value for filter {param}")
        out = [r for r in out if r.get(field) == raw]
    return out
