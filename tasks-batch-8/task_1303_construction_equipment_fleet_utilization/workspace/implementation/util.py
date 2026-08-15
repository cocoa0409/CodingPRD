"""Request validation helpers. All well-formedness failures raise
ERR_INVALID_REQUEST (400); missing body FK references raise
ERR_REF_NOT_FOUND (422)."""
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import store
from errors import ApiError, invalid_request


def rhu(x):
    """Round-half-up a Decimal to a whole integer."""
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def body_json():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise invalid_request("Request body must be a JSON object")
    return data


def req_field(body, name):
    if name not in body or body[name] is None:
        raise invalid_request(f"Missing required field: {name}")
    return body[name]


def as_str(v, name, allow_empty=False):
    if not isinstance(v, str) or (not allow_empty and v == ""):
        raise invalid_request(f"Field {name} must be a non-empty string")
    return v


def as_int(v, name, minimum=None, maximum=None):
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request(f"Field {name} must be an integer")
    if minimum is not None and v < minimum:
        raise invalid_request(f"Field {name} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise invalid_request(f"Field {name} must be <= {maximum}")
    return v


def as_bool(v, name):
    if not isinstance(v, bool):
        raise invalid_request(f"Field {name} must be a boolean")
    return v


def as_enum(v, name, values):
    if not isinstance(v, str) or v not in values:
        raise invalid_request(f"Field {name} must be one of {', '.join(values)}")
    return v


def as_date(v, name):
    """Returns (date_obj, raw_string)."""
    s = as_str(v, name)
    try:
        d = date.fromisoformat(s)
    except ValueError:
        raise invalid_request(f"Field {name} must be an ISO date (YYYY-MM-DD)")
    return d, s


def as_datetime(v, name):
    """Returns (aware datetime UTC, raw_string)."""
    s = as_str(v, name)
    txt = s
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        raise invalid_request(f"Field {name} must be an ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc), s


def as_line_items(v, name="line_items"):
    if not isinstance(v, list) or not (1 <= len(v) <= 20):
        raise invalid_request(f"Field {name} must be an array of 1..20 items")
    items = []
    for it in v:
        if not isinstance(it, dict):
            raise invalid_request(f"Each item of {name} must be an object")
        if "description" not in it or not isinstance(it["description"], str):
            raise invalid_request(f"Each item of {name} requires a description string")
        if "amount_cents" not in it:
            raise invalid_request(f"Each item of {name} requires amount_cents")
        amt = as_int(it["amount_cents"], "amount_cents", minimum=0)
        items.append({"description": it["description"], "amount_cents": amt})
    return items


def check_body_fks(pairs):
    """Priority-4 check: for each (table, body, field) where the field is
    present, non-null and a string, the referenced row must exist."""
    for table, body, field in pairs:
        v = body.get(field)
        if v is None:
            continue
        if isinstance(v, str) and v not in table:
            raise ApiError("ERR_REF_NOT_FOUND", 422,
                           f"Referenced {field} does not exist")


def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            raise invalid_request("offset must be >= 0")
    return limit, offset


def paginate(rows):
    """rows: full filtered list. Returns (page_items, page_meta)."""
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    limit, offset = pagination()
    total = len(rows)
    items = rows[offset:offset + limit]
    meta = {"limit": limit, "offset": offset, "total_count": total,
            "has_more": (offset + len(items)) < total}
    return items, meta
