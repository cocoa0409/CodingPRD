"""Request-shape validation (ladder step 3 — ERR_INVALID_REQUEST)."""

from decimal import Decimal, InvalidOperation

from flask import request

import db
import errors
from errors import fail

_MISSING = object()


def bad(message="The request is malformed."):
    fail(errors.ERR_INVALID_REQUEST, message)


def json_body():
    """The parsed JSON object body, defaulting to {} when absent."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad("The request body must be a JSON object.")
    return data


def _present(body, name):
    return name in body and body[name] is not None


def get_str(body, name, min_len=1, max_len=None, required=True, default=None,
            nullable=False):
    if name not in body or body[name] is None:
        if name in body and body[name] is None and nullable:
            return None
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' is shorter than %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' is longer than %d characters." % (name, max_len))
    return value


def get_int(body, name, minimum=None, maximum=None, required=True, default=None,
            nullable=False):
    if name not in body or body[name] is None:
        if name in body and body[name] is None:
            if nullable:
                return None
            bad("Field '%s' must not be null." % name)
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s." % (name, maximum))
    return value


def get_number(body, name, minimum=None, maximum=None, exclusive_min=None,
               exclusive_max=None, max_decimals=None, required=True,
               default=None, nullable=False):
    if name not in body or body[name] is None:
        if name in body and body[name] is None:
            if nullable:
                return None
            bad("Field '%s' must not be null." % name)
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % name)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad("Field '%s' must be a number." % name)
    if minimum is not None and dec < Decimal(str(minimum)):
        bad("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        bad("Field '%s' must be <= %s." % (name, maximum))
    if exclusive_min is not None and dec <= Decimal(str(exclusive_min)):
        bad("Field '%s' must be greater than %s." % (name, exclusive_min))
    if exclusive_max is not None and dec >= Decimal(str(exclusive_max)):
        bad("Field '%s' must be less than %s." % (name, exclusive_max))
    if max_decimals is not None:
        exponent = dec.as_tuple().exponent
        if not isinstance(exponent, int) or -exponent > max_decimals:
            bad("Field '%s' accepts at most %d decimal places."
                % (name, max_decimals))
    return value


def get_bool(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def get_enum(body, name, allowed, required=True, default=None, nullable=False):
    if name not in body or body[name] is None:
        if name in body and body[name] is None:
            if nullable:
                return None
            bad("Field '%s' must not be null." % name)
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def get_datetime(body, name, required=True, default=None, nullable=False):
    """Returns the raw string as supplied; the value must be a valid instant."""
    if name not in body or body[name] is None:
        if name in body and body[name] is None:
            if nullable:
                return None
            bad("Field '%s' must not be null." % name)
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str) or db.parse_iso(value) is None:
        bad("Field '%s' must be an ISO 8601 timestamp." % name)
    return value


def get_id_ref(body, name, required=True, default=None):
    return get_str(body, name, min_len=1, max_len=None, required=required,
                   default=default)


def get_locale_array(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % name)
    if len(value) < 1 or len(value) > 5:
        bad("Field '%s' must hold 1 to 5 locale tags." % name)
    seen = set()
    for item in value:
        if not isinstance(item, str) or not (2 <= len(item) <= 16):
            bad("Field '%s' must hold BCP-47 locale strings." % name)
        if item in seen:
            bad("Field '%s' must hold distinct locale tags." % name)
        seen.add(item)
    return list(value)


def get_samples(body, name="samples"):
    if name not in body or body[name] is None:
        bad("Field '%s' is required." % name)
    value = body[name]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % name)
    if len(value) < 1 or len(value) > 500:
        bad("Field '%s' must hold 1 to 500 samples." % name)
    samples = []
    for element in value:
        if not isinstance(element, dict):
            bad("Each sample must be an object.")
        observed_at = get_datetime(element, "observed_at")
        download = get_number(element, "download_mbps", exclusive_min=0)
        upload = get_number(element, "upload_mbps", exclusive_min=0)
        latency = get_int(element, "latency_ms", minimum=1)
        samples.append({
            "observed_at": observed_at,
            "download_mbps": download,
            "upload_mbps": upload,
            "latency_ms": latency,
        })
    return samples


# ---------------------------------------------------------------------------
# pagination (PRD §2.3)
# ---------------------------------------------------------------------------

def pagination_params():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad("Query parameter 'offset' must be >= 0.")
    return limit, offset


def paginate(rows, serializer):
    """Apply pagination to an ordered row list and build the meta fields."""
    limit, offset = pagination_params()
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return [serializer(row) for row in page], meta
