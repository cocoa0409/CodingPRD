"""Datetime, rounding and request-shape helpers."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

from errors import err

# --------------------------------------------------------------- datetimes


def parse_dt(value):
    """Parse an ISO-8601 instant; return None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt_dt(instant):
    """ISO 8601 UTC with exactly three fractional digits."""
    if instant is None:
        return None
    inst = instant.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        inst.year, inst.month, inst.day, inst.hour, inst.minute, inst.second,
        inst.microsecond // 1000,
    )


def utc_date(instant):
    return instant.astimezone(timezone.utc).date()


def whole_days_between(earlier, later):
    return int((later - earlier).total_seconds() // 86400)


# ------------------------------------------------------------------ numbers


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


def round_half_up(numerator, denominator=1):
    """Half-up rounding to a whole unit; the service-wide default (PRD 2.6)."""
    quotient = dec(numerator) / dec(denominator)
    return int(quotient.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def ceil_div(numerator, denominator=1):
    quotient = dec(numerator) / dec(denominator)
    return int(quotient.quantize(Decimal(1), rounding=ROUND_CEILING))


def floor_div(numerator, denominator=1):
    quotient = dec(numerator) / dec(denominator)
    return int(quotient.quantize(Decimal(1), rounding=ROUND_FLOOR))


def median_half_up(values):
    """Median of an ascending list of integers, half-up on the even case."""
    count = len(values)
    middle = count // 2
    if count % 2 == 1:
        return round_half_up(values[middle])
    return round_half_up(values[middle - 1] + values[middle], 2)


# ---------------------------------------------------- request shape (rank 5)


def invalid(name, detail):
    return err("ERR_INVALID_REQUEST", "%s %s" % (name, detail))


def get_required(body, name):
    if not isinstance(body, dict) or name not in body or body[name] is None:
        raise invalid(name, "is required.")
    return body[name]


def as_str(value, name, min_len=1, max_len=None):
    if not isinstance(value, str):
        raise invalid(name, "must be a string.")
    if len(value) < min_len:
        raise invalid(name, "must be at least %d characters." % min_len)
    if max_len is not None and len(value) > max_len:
        raise invalid(name, "must be at most %d characters." % max_len)
    return value


def as_int(value, name, minimum=None, maximum=None, gt=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid(name, "must be an integer.")
    if gt is not None and value <= gt:
        raise invalid(name, "must be greater than %s." % gt)
    if minimum is not None and value < minimum:
        raise invalid(name, "must be at least %s." % minimum)
    if maximum is not None and value > maximum:
        raise invalid(name, "must be at most %s." % maximum)
    return value


def as_ratio(value, name, min_inclusive=None, min_exclusive=None,
             max_inclusive=None, max_exclusive=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid(name, "must be a number.")
    number = dec(value)
    if min_inclusive is not None and number < dec(min_inclusive):
        raise invalid(name, "must be at least %s." % min_inclusive)
    if min_exclusive is not None and number <= dec(min_exclusive):
        raise invalid(name, "must be greater than %s." % min_exclusive)
    if max_inclusive is not None and number > dec(max_inclusive):
        raise invalid(name, "must be at most %s." % max_inclusive)
    if max_exclusive is not None and number >= dec(max_exclusive):
        raise invalid(name, "must be below %s." % max_exclusive)
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        raise invalid(name, "must be a boolean.")
    return value


def as_dt(value, name):
    if not isinstance(value, str):
        raise invalid(name, "must be an ISO 8601 timestamp string.")
    parsed = parse_dt(value)
    if parsed is None:
        raise invalid(name, "must be an ISO 8601 timestamp string.")
    return parsed


def as_str_list(value, name, min_len=0):
    if not isinstance(value, list):
        raise invalid(name, "must be an array.")
    for item in value:
        if not isinstance(item, str):
            raise invalid(name, "must be an array of strings.")
    if len(value) < min_len:
        raise invalid(name, "must contain at least %d entries." % min_len)
    return list(value)


# ------------------------------------------------------ enum check (rank 6)


def as_enum(value, name, allowed):
    if value not in allowed:
        raise err("ERR_INVALID_ENUM_VALUE",
                  "%s must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def as_enum_list(value, name, allowed):
    for item in value:
        as_enum(item, name, allowed)
    return value
