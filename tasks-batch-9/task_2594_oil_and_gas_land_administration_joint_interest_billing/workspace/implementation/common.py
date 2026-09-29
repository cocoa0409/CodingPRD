"""Shared primitives: decimal/money helpers, date arithmetic, logical clock,
request-scoped mutation bookkeeping, response envelope and error type."""
import calendar
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g, jsonify

# ---------------------------------------------------------------- decimals

ONE = Decimal("1")
Q6 = Decimal("0.000001")
Q2 = Decimal("0.01")
Q1 = Decimal("0.1")
ZERO6 = Decimal("0.000000")


def dec(value):
    """Coerce an arbitrary JSON scalar to Decimal without float artefacts."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("bool is not numeric")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value).strip())


def q6(value):
    return dec(value).quantize(Q6, rounding=ROUND_HALF_UP)


def q2(value):
    return dec(value).quantize(Q2, rounding=ROUND_HALF_UP)


def q1(value):
    return dec(value).quantize(Q1, rounding=ROUND_HALF_UP)


def rhu(value):
    """Round half up to a whole integer (cents)."""
    return int(dec(value).quantize(ONE, rounding=ROUND_HALF_UP))


def decimal_places(value):
    d = dec(value)
    exp = d.normalize().as_tuple().exponent
    return -exp if exp < 0 else 0


# ---------------------------------------------------------------- dates

def parse_date(text):
    if isinstance(text, date) and not isinstance(text, datetime):
        return text
    if not isinstance(text, str):
        return None
    body = text.strip()
    if len(body) != 10:
        return None
    try:
        return date.fromisoformat(body)
    except ValueError:
        return None


def parse_datetime(text):
    if isinstance(text, datetime):
        return text if text.tzinfo else text.replace(tzinfo=timezone.utc)
    if not isinstance(text, str):
        return None
    body = text.strip()
    if body.endswith("Z") or body.endswith("z"):
        body = body[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(body)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt_ts(moment):
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (moment.microsecond // 1000)


def add_days(base, days):
    return base + timedelta(days=int(days))


def add_months(base, months):
    """Calendar-month arithmetic clamping the day to the target month's last day."""
    total = base.month - 1 + int(months)
    year = base.year + total // 12
    month = total % 12 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(base.day, last))


def month_last_day(year, month):
    return date(year, month, calendar.monthrange(year, month)[1])


def month_key(day):
    return (day.year, day.month)


# ---------------------------------------------------------------- logical clock

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock(object):
    def __init__(self):
        self.current = CLOCK_EPOCH

    def now(self):
        return self.current

    def today(self):
        return self.current.astimezone(timezone.utc).date()

    def set(self, moment):
        self.current = moment.astimezone(timezone.utc)


clock = LogicalClock()


def now_ts():
    return clock.now()


def today():
    return clock.today()


# ---------------------------------------------------------------- errors

class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or humanize(error_id)


def humanize(error_id):
    body = error_id[4:] if error_id.startswith("ERR_") else error_id
    words = body.replace("_", " ").strip().lower()
    return (words[:1].upper() + words[1:] + ".") if words else error_id


# ---------------------------------------------------------------- envelope

ALPHANUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(ALPHANUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_ts(datetime.now(timezone.utc)),
    }


def json_value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return fmt_ts(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def serialize(record, fields):
    return {name: json_value(record.get(name)) for name in fields}


def ok(data, status=200):
    payload = {"meta": base_meta(), "response_type": "object", "data": data or {}}
    return jsonify(payload), status


def ok_list(rows, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    payload = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(payload), 200


def error_response(err):
    payload = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(payload), err.http_status


# ---------------------------------------------------------------- mutation bookkeeping

def touch(record):
    """Refresh updated_at and bump version at most once per request per entity."""
    if record is None:
        return
    record["updated_at"] = now_ts()
    if "version" not in record:
        return
    seen = getattr(g, "_touched", None)
    if seen is None:
        seen = set()
        g._touched = seen
    key = id(record)
    if key in seen:
        return
    seen.add(key)
    record["version"] = record["version"] + 1
