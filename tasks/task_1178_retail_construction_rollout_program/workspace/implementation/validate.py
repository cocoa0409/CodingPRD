"""Request-shape validation (validation priority 12) and body helpers."""
from flask import request

from errors import invalid_request, not_found
from util import parse_date, parse_datetime


def json_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        invalid_request("request body must be a JSON object")
    return body


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        invalid_request("field '%s' is required and must be a string" % field)
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        invalid_request("field '%s' must be a string" % field)
    return v


def req_int(body, field):
    v = body.get(field)
    if not is_int(v):
        invalid_request("field '%s' is required and must be an integer" % field)
    return v


def req_enum(body, field, values):
    v = body.get(field)
    if not isinstance(v, str) or v not in values:
        invalid_request("field '%s' must be one of %s" % (field, sorted(values)))
    return v


def req_date(body, field):
    v = body.get(field)
    try:
        return parse_date(v)
    except (ValueError, TypeError):
        invalid_request("field '%s' must be an ISO date" % field)


def req_datetime(body, field):
    v = body.get(field)
    try:
        return parse_datetime(v)
    except (ValueError, TypeError):
        invalid_request("field '%s' must be an ISO 8601 datetime" % field)


def opt_bool(body, field, default=False):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        invalid_request("field '%s' must be a boolean" % field)
    return v


def body_fk(body, field, collection):
    """Step-4 existence for a body FK. Missing/malformed -> defer to step 12
    by returning None; present-but-unknown -> ERR_NOT_FOUND."""
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        return None
    ent = collection.get(v)
    if ent is None:
        not_found("%s '%s' does not exist" % (field, v))
    return ent


def get_or_404(collection, entity_id, label="resource"):
    ent = collection.get(entity_id)
    if ent is None:
        not_found("%s '%s' does not exist" % (label, entity_id))
    return ent
