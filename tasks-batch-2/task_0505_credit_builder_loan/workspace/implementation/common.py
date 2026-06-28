"""Shared helpers: common-field stamping, pagination, body parsing."""
from flask import request

from db import store
from errors import err, ERR_INVALID_REQUEST

# pagination defaults (PRD §2.3 / SCAFFOLD response_envelope.pagination_defaults)
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def stamp_create(entity, versioned=True):
    """Apply common system fields on create (PRD §2.4)."""
    now = store.now_iso()
    entity["created_at"] = now
    entity["_seq"] = store.next_seq()
    if versioned:
        entity["updated_at"] = now
        entity["version"] = 1
    return entity


def touch(entity):
    """Refresh updated_at and bump version on any mutation (PRD §2.4 / §2.10)."""
    if "version" in entity:
        entity["updated_at"] = store.now_iso()
        entity["version"] += 1


def touch_time_only(entity):
    """Refresh updated_at without bumping version.

    Used by the system clock sweeps (delinquency aging) on the loan: the loan
    `version` is the optimistic-concurrency token for PAYMENT posting (PRD §2.8),
    and the §1.8 cure recipe posts a curing payment carrying the loan version it
    captured at funding — after a delinquency sweep advanced the loan — and that
    payment must succeed. So sweep-driven state advances refresh the timestamp but
    do not advance the payment-OCC version.
    """
    if "version" in entity:
        entity["updated_at"] = store.now_iso()


def get_body():
    if request.method in ("POST", "PATCH"):
        if request.data and len(request.data) > 0:
            data = request.get_json(silent=True)
            if data is None:
                raise err(ERR_INVALID_REQUEST, "Malformed JSON body")
            if not isinstance(data, dict):
                raise err(ERR_INVALID_REQUEST, "Body must be a JSON object")
            return data
        return {}
    return {}


def parse_pagination():
    """Parse limit/offset query params with defaults; clamp/validate (PRD §2.3)."""
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit = PAGE_LIMIT_DEFAULT
    else:
        try:
            limit = int(limit)
        except (ValueError, TypeError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < PAGE_LIMIT_MIN:
            limit = PAGE_LIMIT_MIN
        if limit > PAGE_LIMIT_MAX:
            limit = PAGE_LIMIT_MAX
    if offset is None:
        offset = PAGE_OFFSET_DEFAULT
    else:
        try:
            offset = int(offset)
        except (ValueError, TypeError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items):
    """items: list already sorted by created_at ASC. Returns (page, limit, offset, total)."""
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def sort_by_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e.get("_seq", 0)))
