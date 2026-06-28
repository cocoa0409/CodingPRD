"""Body parsing, schema validation, and pagination helpers.

Schema validation maps to ERR_VALIDATION (422). It is the final validation
family (PRD 2.10), so it runs only after auth/existence/state/business checks
for transition endpoints. For creation endpoints (which have no prior state to
check) it runs as the body-shape gate.
"""
from flask import request

from errors import err
from util import parse_iso


def get_body() -> dict:
    """Return the JSON body as a dict. Missing/empty body -> {}.

    A body that is present but not a JSON object raises ERR_VALIDATION.
    """
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_VALIDATION", "Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object.")
    return data


def require_str(body, field, allow_empty=False):
    val = body.get(field)
    if not isinstance(val, str):
        raise err("ERR_VALIDATION", f"'{field}' must be a string.")
    if not allow_empty and val.strip() == "":
        raise err("ERR_VALIDATION", f"'{field}' must be non-empty.")
    return val


def require_enum(body, field, allowed):
    val = body.get(field)
    if not isinstance(val, str) or val not in allowed:
        raise err("ERR_VALIDATION", f"'{field}' must be one of {sorted(allowed)}.")
    return val


def require_int(body, field, minimum=None):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_VALIDATION", f"'{field}' must be an integer.")
    if minimum is not None and val < minimum:
        raise err("ERR_VALIDATION", f"'{field}' must be >= {minimum}.")
    return val


def require_number(body, field, minimum=None, strict=False):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_VALIDATION", f"'{field}' must be a number.")
    if minimum is not None:
        if strict and not (val > minimum):
            raise err("ERR_VALIDATION", f"'{field}' must be > {minimum}.")
        if not strict and val < minimum:
            raise err("ERR_VALIDATION", f"'{field}' must be >= {minimum}.")
    return val


def require_datetime(body, field):
    raw = body.get(field)
    dt = parse_iso(raw)
    if dt is None:
        raise err("ERR_VALIDATION", f"'{field}' must be a valid ISO 8601 datetime.")
    return dt


def optional_str(body, field):
    val = body.get(field)
    if val is None:
        return None
    if not isinstance(val, str):
        raise err("ERR_VALIDATION", f"'{field}' must be a string.")
    return val


def parse_pagination():
    """Return (limit, offset). Defaults limit=10 (1..100), offset=0 (>=0).

    Out-of-range / malformed pagination params raise ERR_VALIDATION (422).
    """
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise err("ERR_VALIDATION", "'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "'offset' must be an integer.")
        if offset < 0:
            raise err("ERR_VALIDATION", "'offset' must be >= 0.")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending (stable) then slice.

    Returns (page_items, total_count).
    """
    ordered = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
