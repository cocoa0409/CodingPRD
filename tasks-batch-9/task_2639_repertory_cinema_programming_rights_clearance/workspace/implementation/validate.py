"""Schema validation (ladder step 3) and existence resolution (step 4)."""
from flask import request

from errors import ApiError
from store import db
from timeutil import parse_day, parse_hhmm, parse_instant

FORMATS = ("DCP_2K", "DCP_4K", "PRINT_35MM", "PRINT_16MM", "DIGITAL_FILE_PRORES")
TERMS_VARIANTS = ("SLIDING_SCALE_90_10", "PERCENTAGE_FLOOR", "FLAT_FEE")
STRANDS = ("FIRST_RUN", "REPERTORY_SERIES", "FESTIVAL", "SPECIAL_EVENT")
EVENT_TYPES = ("FILMMAKER_QA", "PANEL", "FESTIVAL_SCREENING", "THEMED_INTRO")
PROPOSED_BY = ("CINEMA", "DISTRIBUTOR")
REFUND_DESTINATIONS = ("CASH", "MEMBER_CREDIT")
SETTLEMENT_VARIANTS = ("PROVISIONAL", "FINAL")


def bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Parse the JSON request body.  An absent body is an empty object."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise bad("Request body must be valid JSON.")
    if not isinstance(data, dict):
        raise bad("Request body must be a JSON object.")
    return data


def _present(payload, name):
    if name not in payload or payload[name] is None:
        raise bad("Field '%s' is required." % name)
    return payload[name]


def req_str(payload, name):
    value = _present(payload, name)
    if not isinstance(value, str) or value.strip() == "":
        raise bad("Field '%s' must be a non-empty string." % name)
    return value


def opt_str(payload, name, default=None):
    if name not in payload or payload[name] is None:
        return default
    value = payload[name]
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string." % name)
    return value


def req_int(payload, name, minimum=0, maximum=None):
    value = _present(payload, name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("Field '%s' must be an integer." % name)
    if value < minimum:
        raise bad("Field '%s' must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad("Field '%s' must be <= %d." % (name, maximum))
    return value


def opt_int(payload, name, default=0, minimum=0, maximum=None):
    if name not in payload or payload[name] is None:
        return default
    return req_int(payload, name, minimum, maximum)


def req_bool(payload, name):
    value = _present(payload, name)
    if not isinstance(value, bool):
        raise bad("Field '%s' must be a boolean." % name)
    return value


def opt_bool(payload, name, default=False):
    if name not in payload or payload[name] is None:
        return default
    return req_bool(payload, name)


def req_share(payload, name):
    """An exact decimal fraction between 0 and 1 inclusive."""
    value = _present(payload, name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("Field '%s' must be a number." % name)
    if value < 0 or value > 1:
        raise bad("Field '%s' must be between 0 and 1 inclusive." % name)
    return value


def opt_share(payload, name, default):
    if name not in payload or payload[name] is None:
        return default
    return req_share(payload, name)


def req_enum(payload, name, allowed):
    value = _present(payload, name)
    if not isinstance(value, str) or value not in allowed:
        raise bad("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def req_instant(payload, name):
    value = _present(payload, name)
    parsed = parse_instant(value)
    if parsed is None:
        raise bad("Field '%s' must be an ISO 8601 UTC timestamp." % name)
    return parsed


def req_day(payload, name):
    value = _present(payload, name)
    parsed = parse_day(value)
    if parsed is None:
        raise bad("Field '%s' must be a YYYY-MM-DD date." % name)
    return parsed


def req_hhmm(payload, name):
    value = _present(payload, name)
    parsed = parse_hhmm(value)
    if parsed is None:
        raise bad("Field '%s' must be a venue-local HH:MM time." % name)
    return value


def req_id(payload, name):
    return req_str(payload, name)


def opt_id(payload, name, default=None):
    if name not in payload or payload[name] is None:
        return default
    value = payload[name]
    if not isinstance(value, str) or value.strip() == "":
        raise bad("Field '%s' must be a string id." % name)
    return value


def req_format_list(payload, name):
    value = _present(payload, name)
    if not isinstance(value, list) or len(value) == 0:
        raise bad("Field '%s' must be a non-empty array." % name)
    for item in value:
        if not isinstance(item, str) or item not in FORMATS:
            raise bad("Field '%s' must contain only declared projection formats." % name)
    return list(value)


# --------------------------------------------------------------- existence ---

_COLLECTION_ERRORS = {
    "venues": "ERR_VENUE_NOT_FOUND",
    "distributors": "ERR_DISTRIBUTOR_NOT_FOUND",
    "titles": "ERR_TITLE_NOT_FOUND",
    "bookings": "ERR_BOOKING_NOT_FOUND",
    "offers": "ERR_BOOKING_OFFER_NOT_FOUND",
    "clearances": "ERR_CLEARANCE_NOT_FOUND",
    "assets": "ERR_DCP_ASSET_NOT_FOUND",
    "keys": "ERR_KDM_KEY_NOT_FOUND",
    "showtimes": "ERR_SHOWTIME_NOT_FOUND",
    "events": "ERR_SPECIAL_EVENT_NOT_FOUND",
    "orders": "ERR_TICKET_ORDER_NOT_FOUND",
    "members": "ERR_MEMBER_NOT_FOUND",
    "settlements": "ERR_SETTLEMENT_NOT_FOUND",
}


def find(collection, row_id):
    return getattr(db, collection).get(row_id)


def must_find(collection, row_id):
    row = find(collection, row_id)
    if row is None:
        raise ApiError(_COLLECTION_ERRORS[collection],
                       "No such row for id '%s'." % row_id)
    return row


def rows(collection):
    return list(getattr(db, collection).values())


def insert(collection, row):
    getattr(db, collection)[row["id"]] = row
    return row


# --------------------------------------------------------- query filtering ---

def query_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise bad("Query parameter '%s' must be a boolean." % name)


def query_instant(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    parsed = parse_instant(value)
    if parsed is None:
        raise bad("Query parameter '%s' must be an ISO 8601 UTC timestamp." % name)
    return parsed


def opt_signed_int(payload, name, default):
    """An optional integer that may legitimately be negative (UTC offsets)."""
    if name not in payload or payload[name] is None:
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("Field '%s' must be an integer." % name)
    return value


def opt_positive_share(payload, name, default):
    """An optional share strictly greater than 0 and no more than 1."""
    if name not in payload or payload[name] is None:
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("Field '%s' must be a number." % name)
    if value <= 0 or value > 1:
        raise bad("Field '%s' must be greater than 0 and at most 1." % name)
    return value
