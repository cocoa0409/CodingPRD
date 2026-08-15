"""Request shape validation (stage 4) and pagination parsing (PRD §2.3, §2.8).

Field spec format: (name, kind, required, extra)
  kind: "string" | "int" | "bool" | "enum" | "number" | "datetime" | "string_list" | "enum_list"
  extra: for enum: set of allowed members; for int: (min, max) or (min, None);
         ignored otherwise.
"""

from flask import request

from errors import invalid_request


def get_body(allow_empty=True):
    """Return the JSON body as a dict; {} when absent and allowed."""
    if not request.data:
        if allow_empty:
            return {}
        raise invalid_request("Request body is required")
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise invalid_request("Request body must be valid JSON")
    if not isinstance(body, dict):
        raise invalid_request("Request body must be a JSON object")
    return body


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def validate_shape(body, specs):
    """Validate required fields, types, enum members, integer ranges."""
    out = {}
    for name, kind, required, extra in specs:
        if name not in body or body[name] is None:
            if required:
                raise invalid_request(f"Missing required field: {name}")
            out[name] = None
            continue
        v = body[name]
        if kind == "string":
            if not isinstance(v, str) or v == "":
                raise invalid_request(f"Field {name} must be a non-empty string")
        elif kind == "int":
            if not _is_int(v):
                raise invalid_request(f"Field {name} must be an integer")
            if extra is not None:
                lo, hi = extra
                if lo is not None and v < lo:
                    raise invalid_request(f"Field {name} below minimum {lo}")
                if hi is not None and v > hi:
                    raise invalid_request(f"Field {name} above maximum {hi}")
        elif kind == "bool":
            if not isinstance(v, bool):
                raise invalid_request(f"Field {name} must be a boolean")
        elif kind == "number":
            if not _is_number(v):
                raise invalid_request(f"Field {name} must be a number")
        elif kind == "enum":
            if not isinstance(v, str) or v not in extra:
                raise invalid_request(f"Field {name} must be one of {sorted(extra)}")
        elif kind == "enum_list":
            if (not isinstance(v, list) or len(v) == 0
                    or any((not isinstance(x, str)) or x not in extra for x in v)):
                raise invalid_request(f"Field {name} must be a non-empty list of {sorted(extra)}")
        elif kind == "datetime":
            if not isinstance(v, str):
                raise invalid_request(f"Field {name} must be an ISO-8601 datetime string")
            from db import parse_datetime
            try:
                parse_datetime(v)
            except Exception:
                raise invalid_request(f"Field {name} must be an ISO-8601 datetime string")
        out[name] = v
    return out


def parse_pagination():
    """limit: default 10, 1..100; offset: default 0, >= 0 (PRD §2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            raise invalid_request("offset must be >= 0")
    return limit, offset


def parse_filters(specs):
    """Validate query filter values. specs: {param: enum-set-or-'int'-or-'str'}.
    Returns dict of present filters."""
    out = {}
    for param, kind in specs.items():
        raw = request.args.get(param)
        if raw is None:
            continue
        if kind == "int":
            try:
                out[param] = int(raw)
            except (TypeError, ValueError):
                raise invalid_request(f"Filter {param} must be an integer")
        elif isinstance(kind, (set, frozenset)):
            if raw not in kind:
                raise invalid_request(f"Filter {param} must be one of {sorted(kind)}")
            out[param] = raw
        else:
            out[param] = raw
    return out


def paginate(items, limit, offset):
    """items pre-sorted; returns (page, total_count)."""
    total = len(items)
    return items[offset:offset + limit], total


def sort_by_creation(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
