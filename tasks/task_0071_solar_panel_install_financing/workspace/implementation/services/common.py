from flask import request
from errors import err
from db import db
from response import ok_list

VALID_STATES = {"CA", "NJ", "MA", "TX", "AZ"}


def get_body():
    if request.data and len(request.data) > 0:
        body = request.get_json(silent=True)
        if body is None:
            raise err("ERR_INVALID_REQUEST", "Malformed JSON body.")
        if not isinstance(body, dict):
            raise err("ERR_INVALID_REQUEST", "Body must be a JSON object.")
        return body
    return {}


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def paginate():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit out of range [1,100].")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0.")
    return limit, offset


def list_response(items, filters=None):
    """items: full collection dict values. filters: list of (key, value) predicates."""
    rows = list(items)
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    limit, offset = paginate()
    total = len(rows)
    window = rows[offset:offset + limit]
    return ok_list(window, limit, offset, total)
