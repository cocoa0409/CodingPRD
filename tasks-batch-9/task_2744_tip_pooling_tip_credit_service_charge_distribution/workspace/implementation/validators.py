"""Structural request validation (PRD 2.10 rung 3)."""

import re

from flask import request

from errors import invalid
from store import fmt_date, fmt_instant, parse_date, parse_instant

JOB_ROLE_CODE_RE = re.compile(r"^[A-Z_]{2,40}$")


# ---------------------------------------------------------------------------
# body / query extraction
# ---------------------------------------------------------------------------

def get_body():
    raw = request.get_data(cache=True)
    if raw is None or not raw.strip():
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise invalid("Request body must be a valid JSON object.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid("Request body must be a JSON object.")
    return data


def _reject_unknown(keys, allowed, where):
    for key in keys:
        if key not in allowed:
            raise invalid("Unknown %s field '%s'." % (where, key))


# ---------------------------------------------------------------------------
# scalar coercion
# ---------------------------------------------------------------------------

def as_int(value, name, minimum=0, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise invalid("Field '%s' must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise invalid("Field '%s' must be <= %d." % (name, maximum))
    return value


def as_str(value, name, min_len=1, max_len=None):
    if not isinstance(value, str):
        raise invalid("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        raise invalid("Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise invalid("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        raise invalid("Field '%s' must be a boolean." % name)
    return value


def as_enum(value, name, domain):
    if not isinstance(value, str) or value not in domain:
        raise invalid(
            "Field '%s' must be one of: %s." % (name, ", ".join(sorted(domain)))
        )
    return value


def as_id(value, name):
    if not isinstance(value, str) or not value:
        raise invalid("Field '%s' must be a non-empty identifier string." % name)
    return value


def as_date(value, name):
    return fmt_date(parse_date(value, name))


def as_instant(value, name):
    return fmt_instant(parse_instant(value, name))


# ---------------------------------------------------------------------------
# declarative body parsing
# ---------------------------------------------------------------------------

def parse_body(spec):
    """Parse and validate a JSON body against a field spec.

    ``spec`` is a list of dicts with keys: name, kind, required, default and
    kind-specific bounds.  Returns (values, present) where ``present`` is the
    set of field names supplied with a non-null value.
    """
    body = get_body()
    allowed = set(item["name"] for item in spec)
    _reject_unknown(body.keys(), allowed, "body")

    values = {}
    present = set()
    for item in spec:
        name = item["name"]
        supplied = name in body and body[name] is not None
        if not supplied:
            if item.get("required"):
                raise invalid("Field '%s' is required." % name)
            values[name] = item.get("default")
            continue
        present.add(name)
        values[name] = _coerce(body[name], item)
    return values, present


def _coerce(raw, item):
    name = item["name"]
    kind = item["kind"]
    if kind == "int":
        return as_int(raw, name, item.get("min", 0), item.get("max"))
    if kind == "str":
        return as_str(raw, name, item.get("min_len", 1), item.get("max_len"))
    if kind == "bool":
        return as_bool(raw, name)
    if kind == "enum":
        return as_enum(raw, name, item["domain"])
    if kind == "id":
        return as_id(raw, name)
    if kind == "date":
        return as_date(raw, name)
    if kind == "instant":
        return as_instant(raw, name)
    raise invalid("Field '%s' could not be validated." % name)


# ---------------------------------------------------------------------------
# query string parsing
# ---------------------------------------------------------------------------

def parse_query(spec):
    """Validate the query string of a collection endpoint.

    ``spec`` describes the permitted filters; ``limit`` and ``offset`` are
    always accepted.  Returns (filters, limit, offset).
    """
    allowed = set(item["name"] for item in spec)
    allowed.add("limit")
    allowed.add("offset")
    _reject_unknown(request.args.keys(), allowed, "query")

    limit = _query_int("limit", 10, 1, 100)
    offset = _query_int("offset", 0, 0, None)

    filters = {}
    for item in spec:
        name = item["name"]
        if name not in request.args:
            continue
        raw = request.args.get(name)
        filters[name] = _coerce_query(raw, item)
    return filters, limit, offset


def _query_int(name, default, minimum, maximum):
    if name not in request.args:
        return default
    raw = request.args.get(name)
    if raw is None or raw.strip() == "":
        raise invalid("Query parameter '%s' must be an integer." % name)
    try:
        value = int(raw.strip(), 10)
    except ValueError:
        raise invalid("Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise invalid("Query parameter '%s' must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise invalid("Query parameter '%s' must be <= %d." % (name, maximum))
    return value


def _coerce_query(raw, item):
    name = item["name"]
    kind = item["kind"]
    if kind == "enum":
        return as_enum(raw, name, item["domain"])
    if kind == "bool":
        lowered = (raw or "").strip().lower()
        if lowered in ("true", "1"):
            return True
        if lowered in ("false", "0"):
            return False
        raise invalid("Query parameter '%s' must be a boolean." % name)
    if kind == "int":
        return _query_int(name, None, item.get("min", 0), item.get("max"))
    if kind == "date":
        return as_date(raw, name)
    if kind == "instant":
        return as_instant(raw, name)
    return as_id(raw, name)


# ---------------------------------------------------------------------------
# spec shorthands
# ---------------------------------------------------------------------------

def f(name, kind, required=False, **kw):
    item = {"name": name, "kind": kind, "required": required}
    item.update(kw)
    return item
