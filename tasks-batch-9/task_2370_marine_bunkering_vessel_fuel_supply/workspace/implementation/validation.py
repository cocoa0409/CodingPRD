"""Payload shape validation (PRD 2.8 step 6) and numeric helpers."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from flask import request

from errors import ApiError

_MISSING = object()


def bad(message="The request payload is invalid."):
    return ApiError("ERR_INVALID_REQUEST", message)


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise bad("The request body must be a JSON object.")
    return data


def rnd(value, places):
    """round-half-up to `places` decimals (PRD 2.10)."""
    if value is None:
        return None
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quant = Decimal(1).scaleb(-places)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def num(value):
    """Coerce to Decimal without float artefacts."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def as_float(value):
    if value is None:
        return None
    return float(value)


# --------------------------------------------------------------------------- #
# field readers
# --------------------------------------------------------------------------- #


def _present(data, name, required, default):
    """Return the raw value, or `default` when absent/null (None means absent)."""
    if name not in data or data[name] is None:
        if required:
            raise bad("Field '%s' is required." % name)
        return None, default
    return data[name], default


def v_string(data, name, required=True, default=None, min_len=None, max_len=None):
    value, default = _present(data, name, required, default)
    if value is None:
        return default
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        raise bad("Field '%s' is too short." % name)
    if max_len is not None and len(value) > max_len:
        raise bad("Field '%s' is too long." % name)
    return value


def v_enum(data, name, allowed, required=True, default=None):
    value, default = _present(data, name, required, default)
    if value is None:
        return default
    if not isinstance(value, str) or value not in allowed:
        raise bad("Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def v_bool(data, name, required=True, default=None):
    value, default = _present(data, name, required, default)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise bad("Field '%s' must be a boolean." % name)
    return value


def v_int(data, name, required=True, default=None, min_value=None, max_value=None):
    value, default = _present(data, name, required, default)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("Field '%s' must be an integer." % name)
    if min_value is not None and value < min_value:
        raise bad("Field '%s' must be >= %s." % (name, min_value))
    if max_value is not None and value > max_value:
        raise bad("Field '%s' must be <= %s." % (name, max_value))
    return value


def v_decimal(
    data,
    name,
    scale,
    required=True,
    default=None,
    positive=False,
    min_value=None,
):
    value, default = _present(data, name, required, default)
    if value is None:
        return rnd(default, scale) if default is not None else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("Field '%s' must be a number." % name)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        raise bad("Field '%s' must be a number." % name)
    if not dec.is_finite():
        raise bad("Field '%s' must be a finite number." % name)
    exponent = dec.as_tuple().exponent
    if exponent < -scale:
        raise bad("Field '%s' allows at most %d decimal places." % (name, scale))
    if positive and dec <= 0:
        raise bad("Field '%s' must be strictly greater than zero." % name)
    if min_value is not None and dec < Decimal(str(min_value)):
        raise bad("Field '%s' must be >= %s." % (name, min_value))
    return rnd(dec, scale)


def parse_dt(value, name):
    if not isinstance(value, str):
        raise bad("Field '%s' must be an ISO 8601 datetime string." % name)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise bad("Field '%s' must be an ISO 8601 datetime string." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def v_datetime(data, name, required=True, default=None):
    value, default = _present(data, name, required, default)
    if value is None:
        return default
    return parse_dt(value, name)


# --------------------------------------------------------------------------- #
# query parameters
# --------------------------------------------------------------------------- #


def pagination():
    """limit/offset with the PRD 2.3 defaults and bounds."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise bad("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise bad("Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise bad("Query parameter 'offset' must be >= 0.")
    return limit, offset


def q_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        raise bad("Query parameter '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def q_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def apply_page(rows, limit, offset):
    return rows[offset : offset + limit]
