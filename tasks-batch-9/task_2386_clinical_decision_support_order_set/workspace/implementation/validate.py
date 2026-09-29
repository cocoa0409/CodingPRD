"""Schema validation helpers — every failure here is ERR_INVALID_REQUEST (PRD §2.7 step 6)."""
from datetime import datetime, timezone

from flask import request

from errors import ApiError

_MISSING = object()


def body():
    """The JSON request body as a dict (an absent body behaves as {})."""
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return payload


def _fail(field, detail):
    raise ApiError("ERR_INVALID_REQUEST", "%s %s" % (field, detail))


def raw(data, field, default=_MISSING, required=False):
    if field in data and data[field] is not None:
        return data[field]
    if field in data and data[field] is None and not required:
        return None if default is _MISSING else default
    if required:
        _fail(field, "is required")
    return None if default is _MISSING else default


def string(data, field, required=False, default=None, allow_empty=False):
    if field not in data or data[field] is None:
        if required:
            _fail(field, "is required")
        return default
    value = data[field]
    if not isinstance(value, str):
        _fail(field, "must be a string")
    if not allow_empty and value.strip() == "" and required:
        _fail(field, "must not be empty")
    return value


def enum(data, field, allowed, required=False, default=None):
    value = string(data, field, required=required, default=None)
    if value is None:
        return default
    if value not in allowed:
        _fail(field, "must be one of %s" % ", ".join(allowed))
    return value


def boolean(data, field, required=False, default=None):
    if field not in data or data[field] is None:
        if required:
            _fail(field, "is required")
        return default
    value = data[field]
    if not isinstance(value, bool):
        _fail(field, "must be a boolean")
    return value


def integer(data, field, required=False, default=None, minimum=None):
    if field not in data or data[field] is None:
        if required:
            _fail(field, "is required")
        return default
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(field, "must be an integer")
    if minimum is not None and value < minimum:
        _fail(field, "must be at least %d" % minimum)
    return value


def array(data, field, required=False, default=None, min_len=None):
    if field not in data or data[field] is None:
        if required:
            _fail(field, "is required")
        return default
    value = data[field]
    if not isinstance(value, list):
        _fail(field, "must be an array")
    if min_len is not None and len(value) < min_len:
        _fail(field, "must contain at least %d element(s)" % min_len)
    return value


def obj(data, field, required=False, default=None):
    if field not in data or data[field] is None:
        if required:
            _fail(field, "is required")
        return default
    value = data[field]
    if not isinstance(value, dict):
        _fail(field, "must be an object")
    return value


def parse_instant(value, field):
    if not isinstance(value, str):
        _fail(field, "must be an ISO 8601 timestamp string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        _fail(field, "must be a valid ISO 8601 timestamp")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def instant(data, field, required=False, default=None):
    if field not in data or data[field] is None:
        if required:
            _fail(field, "is required")
        return default
    return parse_instant(data[field], field)


def query_instant(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    try:
        return parse_instant(value, name)
    except ApiError:
        return None


def query_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    return None


def query_int(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def citations(data, field, required=True, empty_error=None, allow_empty=False):
    """Validate an evidence_citations array (PRD §3.1 / §3.9 shape).

    ``allow_empty`` defers the emptiness verdict to the caller, which matters at
    attestation where an empty array is an evidence failure evaluated at step 15
    rather than a schema failure at step 6 (PRD §2.7).
    """
    if field not in data or data[field] is None:
        if required:
            _fail(field, "is required")
        return None
    value = data[field]
    if not isinstance(value, list):
        _fail(field, "must be an array")
    if len(value) == 0 and not allow_empty:
        if empty_error is not None:
            raise ApiError(empty_error, "At least one evidence citation is required")
        _fail(field, "must contain at least 1 element(s)")
    for entry in value:
        if not isinstance(entry, dict):
            _fail(field, "entries must be objects")
        if not isinstance(entry.get("citation"), str) or entry.get("citation") is None:
            _fail(field + ".citation", "is required and must be a string")
        if not isinstance(entry.get("peer_reviewed"), bool):
            _fail(field + ".peer_reviewed", "is required and must be a boolean")
        if "doi" in entry and entry["doi"] is not None and not isinstance(entry["doi"], str):
            _fail(field + ".doi", "must be a string")
        if "publication_year" in entry and entry["publication_year"] is not None:
            if isinstance(entry["publication_year"], bool) or not isinstance(entry["publication_year"], int):
                _fail(field + ".publication_year", "must be an integer")
    return value
