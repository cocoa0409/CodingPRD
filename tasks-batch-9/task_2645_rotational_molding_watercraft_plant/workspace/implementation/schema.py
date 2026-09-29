"""Request-body parsing and the three schema passes (types, enums, bounds).

The three passes are registered on the shared check pipeline at the ladder
priorities 20 (ERR_VALIDATION), 21 (ERR_INVALID_ENUM_VALUE) and
22 (ERR_INVALID_QUANTITY) so their relative order is never in doubt.
"""
import json
from decimal import Decimal, InvalidOperation

from flask import request

from core import dec_places, parse_date, parse_ts, q
from errors import fail


def body_json():
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except Exception:
        fail("ERR_VALIDATION", "Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object.")
    return parsed


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return _is_int(v) or isinstance(v, Decimal) or isinstance(v, float)


def _dec(v):
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def pass_types(body, spec):
    """Required fields, JSON types, string lengths, declared decimal places,
    date and timestamp parsing.  All failures are ERR_VALIDATION."""
    for name, rule in spec.items():
        present = name in body and body[name] is not None
        if not present:
            if rule.get("required"):
                fail("ERR_VALIDATION", "Field '%s' is required." % name)
            continue
        v = body[name]
        t = rule["type"]
        if t == "string" or t == "enum":
            if not isinstance(v, str):
                fail("ERR_VALIDATION", "Field '%s' must be a string." % name)
            if "min_len" in rule and len(v) < rule["min_len"]:
                fail("ERR_VALIDATION", "Field '%s' is too short." % name)
            if "max_len" in rule and len(v) > rule["max_len"]:
                fail("ERR_VALIDATION", "Field '%s' is too long." % name)
        elif t == "int":
            if not _is_int(v):
                fail("ERR_VALIDATION", "Field '%s' must be an integer." % name)
        elif t == "dec":
            if not _is_num(v):
                fail("ERR_VALIDATION", "Field '%s' must be a number." % name)
            try:
                d = _dec(v)
            except (InvalidOperation, ValueError):
                fail("ERR_VALIDATION", "Field '%s' must be a number." % name)
            if not d.is_finite():
                fail("ERR_VALIDATION", "Field '%s' must be a number." % name)
            if dec_places(d) > rule.get("places", 2):
                fail(
                    "ERR_VALIDATION",
                    "Field '%s' carries more than %d decimal places."
                    % (name, rule.get("places", 2)),
                )
        elif t == "bool":
            if not isinstance(v, bool):
                fail("ERR_VALIDATION", "Field '%s' must be a boolean." % name)
        elif t == "date" or t == "ts":
            if not isinstance(v, str):
                fail("ERR_VALIDATION", "Field '%s' must be a string." % name)
        elif t == "array":
            if not isinstance(v, list):
                fail("ERR_VALIDATION", "Field '%s' must be an array." % name)
            if "min_items" in rule and len(v) < rule["min_items"]:
                fail("ERR_VALIDATION", "Field '%s' has too few elements." % name)
            if "max_items" in rule and len(v) > rule["max_items"]:
                fail("ERR_VALIDATION", "Field '%s' has too many elements." % name)
        elif t == "object":
            if not isinstance(v, dict):
                fail("ERR_VALIDATION", "Field '%s' must be an object." % name)


def pass_enums(body, spec):
    for name, rule in spec.items():
        if rule["type"] != "enum":
            continue
        if name not in body or body[name] is None:
            continue
        if body[name] not in rule["values"]:
            fail("ERR_INVALID_ENUM_VALUE", "Field '%s' has an unrecognised value." % name)


def pass_bounds(body, spec):
    for name, rule in spec.items():
        if name not in body or body[name] is None:
            continue
        t = rule["type"]
        if t not in ("int", "dec"):
            continue
        err = rule.get("bound_error", "ERR_INVALID_QUANTITY")
        v = _dec(body[name])
        for key, op, text in (
            ("min", "ge", "at least"), ("max", "le", "at most"),
            ("gt", "gt", "greater than"), ("lt", "lt", "less than"),
        ):
            if key not in rule:
                continue
            limit = _dec(rule[key])
            ok = {
                "ge": v >= limit, "le": v <= limit,
                "gt": v > limit, "lt": v < limit,
            }[op]
            if not ok:
                fail(err, "Field '%s' must be %s %s." % (name, text, rule[key]))


def pass_dates(body, spec):
    """Ladder rung 23: every timestamp parses as ISO 8601 UTC and every date as
    YYYY-MM-DD.  Evaluated after the enum and bound passes, exactly as declared."""
    for name, rule in spec.items():
        if name not in body or body[name] is None:
            continue
        v = body[name]
        if rule["type"] == "date":
            if not isinstance(v, str) or parse_date(v) is None:
                fail("ERR_VALIDATION", "Field '%s' must be a YYYY-MM-DD date." % name)
        elif rule["type"] == "ts":
            if not isinstance(v, str) or parse_ts(v) is None:
                fail("ERR_VALIDATION",
                     "Field '%s' must be an ISO 8601 UTC instant." % name)


def coerce(body, spec):
    """Materialise validated values, applying declared defaults and rounding
    every decimal to its declared precision."""
    out = {}
    for name, rule in spec.items():
        present = name in body and body[name] is not None
        if not present:
            if "default" in rule:
                d = rule["default"]
                if rule["type"] == "dec" and d is not None:
                    d = q(Decimal(str(d)), rule.get("places", 2))
                out[name] = d
            else:
                out[name] = None
            continue
        v = body[name]
        t = rule["type"]
        if t == "dec":
            out[name] = q(_dec(v), rule.get("places", 2))
        elif t == "date":
            out[name] = parse_date(v)
        elif t == "ts":
            out[name] = parse_ts(v)
        else:
            out[name] = v
    return out


def add_schema(checks, body, spec):
    checks.add(20, lambda: pass_types(body, spec))
    checks.add(21, lambda: pass_enums(body, spec))
    checks.add(22, lambda: pass_bounds(body, spec))
    checks.add(23, lambda: pass_dates(body, spec))


def enum_filter(name, values):
    """Read an exact-match enum query filter, rejecting unknown members."""
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in values:
        fail("ERR_INVALID_ENUM_VALUE", "Filter '%s' has an unrecognised value." % name)
    return raw


def str_filter(name):
    return request.args.get(name)


def bool_filter(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    low = raw.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    fail("ERR_INVALID_ENUM_VALUE", "Filter '%s' must be true or false." % name)


def date_filter(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    d = parse_date(raw)
    if d is None:
        fail("ERR_VALIDATION", "Filter '%s' must be a YYYY-MM-DD date." % name)
    return d


def ts_filter(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    t = parse_ts(raw)
    if t is None:
        fail("ERR_VALIDATION", "Filter '%s' must be an ISO 8601 UTC instant." % name)
    return t
