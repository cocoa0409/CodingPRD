"""Request-shape validation (PRD §2.10 step 3) and existence resolution (step 4)."""

from flask import request

from errors import fail
from store import STORE, parse_iso_date, parse_iso_datetime

MISSING = object()


# ------------------------------------------------------------------- body


def json_body():
    """Parse the JSON body.  An absent/empty body is an empty object so that
    action endpoints which declare no input can be called without a payload."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "request body is not valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def _present(body, name, required):
    value = body.get(name, MISSING)
    if value is MISSING or value is None:
        if required:
            fail("ERR_INVALID_REQUEST", "missing required field: %s" % name)
        return MISSING
    return value


def field_str(body, name, required=True, min_len=1, max_len=None, default=None):
    value = _present(body, name, required)
    if value is MISSING:
        return default
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string" % name)
    if min_len is not None and len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "%s must be at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "%s must be at most %d characters" % (name, max_len))
    return value


def field_int(body, name, required=True, minimum=None, maximum=None, default=None):
    value = _present(body, name, required)
    if value is MISSING:
        return default
    if isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if isinstance(value, int):
        result = value
    elif isinstance(value, float) and float(value).is_integer():
        result = int(value)
    else:
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if minimum is not None and result < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %s" % (name, minimum))
    if maximum is not None and result > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %s" % (name, maximum))
    return result


def field_number(
    body,
    name,
    required=True,
    minimum=None,
    maximum=None,
    exclusive_minimum=None,
    exclusive_maximum=None,
    default=None,
):
    value = _present(body, name, required)
    if value is MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "%s must be a number" % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %s" % (name, maximum))
    if exclusive_minimum is not None and value <= exclusive_minimum:
        fail("ERR_INVALID_REQUEST", "%s must be > %s" % (name, exclusive_minimum))
    if exclusive_maximum is not None and value >= exclusive_maximum:
        fail("ERR_INVALID_REQUEST", "%s must be < %s" % (name, exclusive_maximum))
    return value


def field_bool(body, name, required=True, default=None):
    value = _present(body, name, required)
    if value is MISSING:
        return default
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean" % name)
    return value


def field_enum(body, name, values, required=True, default=None):
    value = _present(body, name, required)
    if value is MISSING:
        return default
    if not isinstance(value, str) or value not in values:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (name, ", ".join(values)))
    return value


def field_date(body, name, required=True, default=None):
    value = _present(body, name, required)
    if value is MISSING:
        return default
    parsed = parse_iso_date(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO calendar date (YYYY-MM-DD)" % name)
    return value.strip()


def field_datetime(body, name, required=True, default=None):
    value = _present(body, name, required)
    if value is MISSING:
        return default
    parsed = parse_iso_datetime(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 UTC instant" % name)
    return value.strip()


def field_str_array(body, name, required=True, default=None):
    value = _present(body, name, required)
    if value is MISSING:
        return list(default) if default is not None else None
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        fail("ERR_INVALID_REQUEST", "%s must be an array of strings" % name)
    return list(value)


# ------------------------------------------------------------ query params


def pagination_args():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def enum_arg(name, values):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in values:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (name, ", ".join(values)))
    return value


def str_arg(name):
    return request.args.get(name)


def bool_arg(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "%s must be true or false" % name)


# ------------------------------------------------------------- existence


def get_event(event_id):
    record = STORE.events.get(event_id)
    if record is None:
        fail("ERR_EVENT_NOT_FOUND", "event %s does not exist" % event_id)
    return record


def get_hotel(hotel_id):
    record = STORE.hotels.get(hotel_id)
    if record is None:
        fail("ERR_HOTEL_NOT_FOUND", "hotel %s does not exist" % hotel_id)
    return record


def get_block(block_id):
    record = STORE.hotel_blocks.get(block_id)
    if record is None:
        fail("ERR_HOTEL_BLOCK_NOT_FOUND", "hotel block %s does not exist" % block_id)
    return record


def get_sub_block(sub_block_id):
    record = STORE.sub_blocks.get(sub_block_id)
    if record is None:
        fail("ERR_SUB_BLOCK_NOT_FOUND", "sub-block %s does not exist" % sub_block_id)
    return record


def get_attendee(attendee_id):
    record = STORE.attendees.get(attendee_id)
    if record is None:
        fail("ERR_ATTENDEE_NOT_FOUND", "attendee %s does not exist" % attendee_id)
    return record


def get_reservation(reservation_id):
    record = STORE.reservations.get(reservation_id)
    if record is None:
        fail("ERR_RESERVATION_NOT_FOUND", "reservation %s does not exist" % reservation_id)
    return record


def get_reduction(reduction_id):
    record = STORE.reductions.get(reduction_id)
    if record is None:
        fail("ERR_REDUCTION_NOT_FOUND", "attrition reduction %s does not exist" % reduction_id)
    return record


def get_vendor(vendor_id):
    record = STORE.vendors.get(vendor_id)
    if record is None:
        fail("ERR_VENDOR_NOT_FOUND", "rogue vendor %s does not exist" % vendor_id)
    return record


def get_invoice(invoice_id):
    record = STORE.invoices.get(invoice_id)
    if record is None:
        fail("ERR_INVOICE_NOT_FOUND", "commission invoice %s does not exist" % invoice_id)
    return record
