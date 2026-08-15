"""Request-shape validation (PRD 2.8 tier 5) and shared lookup helpers.

Field spec format: ``{name: (kind, required)}`` with kind in
``string | int | number | datetime | array | bool``.  Optional fields may be
null/absent.  Unknown fields are rejected.  Enum membership is checked
separately with ``check_enum`` so it surfaces as ERR_INVALID_ENUM.
"""

from errors import ApiError
from timeutil import parse_instant


def _type_ok(kind, value):
    if kind == "string":
        return isinstance(value, str)
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "datetime":
        return parse_instant(value) is not None
    if kind == "array":
        return isinstance(value, list)
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "any":
        return True
    return False


def check_body(body, spec):
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "request body must be a JSON object")
    for key in body:
        if key not in spec:
            raise ApiError("ERR_INVALID_REQUEST", "unknown field: %s" % key)
    for name, (kind, required) in spec.items():
        if name not in body or body[name] is None:
            if required:
                raise ApiError("ERR_INVALID_REQUEST", "missing required field: %s" % name)
            continue
        if not _type_ok(kind, body[name]):
            raise ApiError("ERR_INVALID_REQUEST", "field %s has the wrong type" % name)
    return body


def check_enum(body, name, values):
    if name in body and body[name] is not None and body[name] not in values:
        raise ApiError("ERR_INVALID_ENUM", "field %s carries an undeclared value" % name)


def get_or_404(collection, rid):
    row = collection.get(rid) if isinstance(rid, str) else None
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "resource not found: %s" % rid)
    return row


def resolve_body_id(collection, body, name):
    """Existence for an id appearing in the body (tier 4).  Absent/None = skip."""
    rid = body.get(name)
    if rid is None:
        return None
    return get_or_404(collection, rid)


def resolve_ids(body, *pairs):
    """Tier-4 existence for body id fields, left to right in ``pairs`` order.
    Returns {field: row}.  Absent/None fields are skipped (shape tier catches
    a missing required field later)."""
    out = {}
    if not isinstance(body, dict):
        return out
    for collection, field in pairs:
        rid = body.get(field)
        if rid is not None:
            out[field] = get_or_404(collection, rid)
    return out
