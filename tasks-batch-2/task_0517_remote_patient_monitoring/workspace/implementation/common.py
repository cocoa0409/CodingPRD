"""Shared request helpers: pagination, body parsing, sorting."""
from flask import request

import errors

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def get_json_body():
    """Return the parsed JSON body as a dict, or {} when absent.

    A body that is present but not a JSON object raises ERR_INVALID_REQUEST.
    """
    if request.content_length in (None, 0) and not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        # No body / unparseable -> treat as empty for action endpoints.
        if request.data:
            raise errors.invalid_request("Request body is not valid JSON.")
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return data


def parse_pagination():
    """Parse limit/offset query params (PRD §2.3).

    limit defaults to 10, min 1, max 100. offset defaults to 0.
    Out-of-domain values are rejected with ERR_INVALID_REQUEST.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.invalid_request("limit must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise errors.invalid_request(
                "limit must be between 1 and 100."
            )

    if offset_raw is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.invalid_request("offset must be an integer.")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0.")

    return limit, offset


def sort_by_created(records):
    """Sort by created_at ASC, tie-broken by creation sequence (PRD §2.3)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def paginate(records, limit, offset):
    """Return (page_items, total_count)."""
    total = len(records)
    page = records[offset:offset + limit]
    return page, total
