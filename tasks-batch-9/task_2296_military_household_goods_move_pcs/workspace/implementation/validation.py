"""Request-body well-formedness helpers — ladder step 3 (PRD §2.5)."""

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from response import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)

MARKET_CODE_RE = re.compile(r"^MKT-[A-Z]{3}$")
SCAC_RE = re.compile(r"^[A-Z]{4}$")
DOD_ID_RE = re.compile(r"^[0-9]{10}$")

_MISSING = object()


def bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def get_body():
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise bad("Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise bad("Request body must be a JSON object.")
    return body


def present(body, name):
    return name in body and body[name] is not None


def _require(body, name):
    if not present(body, name):
        raise bad("Field '%s' is required." % name)
    return body[name]


# --------------------------------------------------------------------------- str


def opt_str(body, name, default=None, min_len=None, max_len=None):
    if not present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        raise bad("Field '%s' is shorter than %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad("Field '%s' is longer than %d characters." % (name, max_len))
    return value


def req_str(body, name, min_len=1, max_len=None):
    _require(body, name)
    return opt_str(body, name, min_len=min_len, max_len=max_len)


def req_pattern(body, name, pattern, description):
    value = req_str(body, name)
    if not pattern.match(value):
        raise bad("Field '%s' must %s." % (name, description))
    return value


# -------------------------------------------------------------------------- enum


def opt_enum(body, name, allowed, default=None):
    if not present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        raise bad("Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def req_enum(body, name, allowed):
    _require(body, name)
    return opt_enum(body, name, allowed)


# ------------------------------------------------------------------------ number


def _as_int(name, value):
    if isinstance(value, bool):
        raise bad("Field '%s' must be an integer." % name)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    raise bad("Field '%s' must be an integer." % name)


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if not present(body, name):
        return default
    value = _as_int(name, body[name])
    if minimum is not None and value < minimum:
        raise bad("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad("Field '%s' must be <= %s." % (name, maximum))
    return value


def req_int(body, name, minimum=None, maximum=None):
    _require(body, name)
    return opt_int(body, name, minimum=minimum, maximum=maximum)


def _as_decimal(name, value):
    if isinstance(value, bool):
        raise bad("Field '%s' must be a number." % name)
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            raise bad("Field '%s' must be a number." % name)
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except (InvalidOperation, ValueError):
            raise bad("Field '%s' must be a number." % name)
    raise bad("Field '%s' must be a number." % name)


def opt_decimal(body, name, default=None, minimum=None, maximum=None):
    if not present(body, name):
        return default
    value = _as_decimal(name, body[name])
    if minimum is not None and value < Decimal(str(minimum)):
        raise bad("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > Decimal(str(maximum)):
        raise bad("Field '%s' must be <= %s." % (name, maximum))
    return value


def req_decimal(body, name, minimum=None, maximum=None):
    _require(body, name)
    return opt_decimal(body, name, minimum=minimum, maximum=maximum)


def opt_float(body, name, default=None, minimum=None, maximum=None):
    value = opt_decimal(body, name, default=None, minimum=minimum, maximum=maximum)
    if value is None:
        return default
    return float(value)


# ----------------------------------------------------------------------- boolean


def opt_bool(body, name, default=None):
    if not present(body, name):
        return default
    value = body[name]
    if not isinstance(value, bool):
        raise bad("Field '%s' must be a boolean." % name)
    return value


def req_bool(body, name):
    _require(body, name)
    return opt_bool(body, name)


# ---------------------------------------------------------------------- datetime


def parse_dt(value, name):
    if not isinstance(value, str) or not value.strip():
        raise bad("Field '%s' must be an ISO 8601 datetime string." % name)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            raise bad("Field '%s' must be an ISO 8601 datetime string." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def opt_dt(body, name, default=None):
    if not present(body, name):
        return default
    return parse_dt(body[name], name)


def req_dt(body, name):
    _require(body, name)
    return parse_dt(body[name], name)


# ------------------------------------------------------------------------- array


def req_list(body, name):
    _require(body, name)
    value = body[name]
    if not isinstance(value, list):
        raise bad("Field '%s' must be an array." % name)
    return value


def validate_room_estimates(raw):
    """Every element must carry room_name and cube_feet (ladder step 3)."""
    cleaned = []
    for element in raw:
        if not isinstance(element, dict):
            raise bad("Every room_estimates entry must be an object.")
        if "room_name" not in element or element["room_name"] is None:
            raise bad("Every room_estimates entry must carry room_name.")
        if "cube_feet" not in element or element["cube_feet"] is None:
            raise bad("Every room_estimates entry must carry cube_feet.")
        if not isinstance(element["room_name"], str):
            raise bad("room_name must be a string.")
        cube = _as_decimal("cube_feet", element["cube_feet"])
        if cube <= 0:
            raise bad("cube_feet must be greater than zero.")
        cleaned.append({"room_name": element["room_name"], "cube_feet": cube})
    return cleaned


def validate_trip_tickets(raw):
    """Every element must carry the five declared keys (ladder step 3)."""
    cleaned = []
    seen = set()
    for element in raw:
        if not isinstance(element, dict):
            raise bad("Every trip_tickets entry must be an object.")
        for key in ("trip_number", "full_lbs", "empty_lbs", "ticket_source", "certified"):
            if key not in element or element[key] is None:
                raise bad("Every trip_tickets entry must carry %s." % key)
        trip_number = _as_int("trip_number", element["trip_number"])
        full_lbs = _as_int("full_lbs", element["full_lbs"])
        empty_lbs = _as_int("empty_lbs", element["empty_lbs"])
        if full_lbs < 0 or empty_lbs < 0:
            raise bad("Weight ticket figures may not be negative.")
        if not isinstance(element["ticket_source"], str):
            raise bad("ticket_source must be a string.")
        if not isinstance(element["certified"], bool):
            raise bad("certified must be a boolean.")
        if trip_number in seen:
            raise bad("trip_number must be unique within trip_tickets.")
        seen.add(trip_number)
        cleaned.append(
            {
                "trip_number": trip_number,
                "full_lbs": full_lbs,
                "empty_lbs": empty_lbs,
                "ticket_source": element["ticket_source"],
                "certified": element["certified"],
            }
        )
    return cleaned


# -------------------------------------------------------------------- pagination

FILTER_FIELDS = (
    "status",
    "movement_status",
    "weight_recon_status",
    "move_type",
    "market_code",
    "is_short_notice",
    "owner",
    "sit_type",
    "disposition",
    "notification_type",
    "order_id",
    "entitlement_id",
    "tsp_id",
    "capacity_block_id",
)

BOOL_FILTERS = ("is_short_notice",)


def parse_pagination():
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise bad("Query parameter 'limit' must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise bad(
                "Query parameter 'limit' must be between %d and %d."
                % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT)
            )
    raw_offset = request.args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise bad("Query parameter 'offset' may not be negative.")
    return limit, offset


def parse_filters():
    filters = {}
    for name in FILTER_FIELDS:
        raw = request.args.get(name)
        if raw is None or raw == "":
            continue
        if name in BOOL_FILTERS:
            lowered = raw.strip().lower()
            if lowered in ("true", "1"):
                filters[name] = True
            elif lowered in ("false", "0"):
                filters[name] = False
            else:
                raise bad("Query parameter '%s' must be a boolean." % name)
        else:
            filters[name] = raw
    return filters


def apply_filters(records, filters):
    if not filters:
        return records
    out = []
    for record in records:
        keep = True
        for key, wanted in filters.items():
            if key not in record or record.get(key) != wanted:
                keep = False
                break
        if keep:
            out.append(record)
    return out
