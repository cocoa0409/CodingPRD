"""Request-shape validation (gate 2). Unknown/system fields are ignored.

Field spec format: (name, kind, required, options...)
kinds: "str", "int", "num", "bool", "dt" (ISO datetime), "date", "enum",
       "quarter" (YYYY-Qn label)
options: enum=[...], min=..., max=...
"""
from errors import err
from util import parse_dt, parse_date, parse_quarter_label


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def validate(body, specs):
    """Validate body against specs; return dict of cleaned values.

    Unknown fields and system/computed fields in the body are ignored.
    """
    out = {}
    for spec in specs:
        name, kind, required = spec[0], spec[1], spec[2]
        opts = spec[3] if len(spec) > 3 else {}
        present = name in body and body[name] is not None
        if not present:
            if required:
                raise err("ERR_VALIDATION", f"Missing required field: {name}")
            continue
        v = body[name]
        if kind == "str":
            if not isinstance(v, str):
                raise err("ERR_VALIDATION", f"Field {name} must be a string")
        elif kind == "int":
            if not _is_int(v):
                raise err("ERR_VALIDATION", f"Field {name} must be an integer")
        elif kind == "num":
            if not _is_num(v):
                raise err("ERR_VALIDATION", f"Field {name} must be a number")
            v = float(v)
        elif kind == "bool":
            if not isinstance(v, bool):
                raise err("ERR_VALIDATION", f"Field {name} must be a boolean")
        elif kind == "dt":
            dt = parse_dt(v)
            if dt is None:
                raise err("ERR_VALIDATION", f"Field {name} must be an ISO 8601 datetime")
            v = dt
        elif kind == "date":
            d = parse_date(v)
            if d is None:
                raise err("ERR_VALIDATION", f"Field {name} must be a YYYY-MM-DD date")
            v = d
        elif kind == "quarter":
            q = parse_quarter_label(v)
            if q is None:
                raise err("ERR_VALIDATION", f"Field {name} must match YYYY-Qn")
            # keep the canonical label
            v = f"{q[0]:04d}-Q{q[1]}"
        elif kind == "enum":
            allowed = opts.get("enum", [])
            if not isinstance(v, str) or v not in allowed:
                raise err("ERR_VALIDATION",
                          f"Field {name} must be one of {', '.join(allowed)}")
        else:
            raise AssertionError(f"unknown kind {kind}")
        if "min" in opts and v < opts["min"]:
            raise err("ERR_VALIDATION", f"Field {name} below minimum {opts['min']}")
        if "max" in opts and v > opts["max"]:
            raise err("ERR_VALIDATION", f"Field {name} above maximum {opts['max']}")
        out[name] = v
    return out


def parse_pagination(args):
    """limit/offset query params: default 10/0, limit in [1,100], offset >= 0."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "limit must be an integer")
        if str(raw_limit).strip() != str(limit) and not raw_limit.strip().lstrip("+").isdigit():
            raise err("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_VALIDATION", "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise err("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset
