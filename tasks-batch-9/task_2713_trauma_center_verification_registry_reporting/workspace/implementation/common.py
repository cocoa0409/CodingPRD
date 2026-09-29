"""Arithmetic, timestamp and record helpers (PRD sections 2.4 and 2.6)."""
import datetime
from decimal import Decimal, ROUND_HALF_UP

from store import db, new_id

UTC = datetime.timezone.utc


def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places=2):
    """Round half up to `places` decimals."""
    quant = Decimal(1).scaleb(-places)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def num(value, places=2):
    """Round half up and return a JSON number carried to `places` decimals."""
    return float(rhu(value, places))


def quantize_quarter(value):
    """Snap to the nearest quarter: multiply by four, round half up, divide by four."""
    return rhu(D(value) * 4, 0) / Decimal(4)


def wall_now():
    return datetime.datetime.now(tz=UTC)


def parse_dt(raw):
    """Parse an ISO 8601 instant; returns None when unparseable."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        value = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def iso(value):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if value is None:
        return None
    value = value.astimezone(UTC)
    return "%s.%03dZ" % (value.strftime("%Y-%m-%dT%H:%M:%S"), value.microsecond // 1000)


def days(count):
    return datetime.timedelta(days=count)


def new_record(versioned=True):
    now = wall_now()
    record = {"id": new_id(), "created_at": now, "_seq": db.next_seq()}
    if versioned:
        record["updated_at"] = now
        record["version"] = 1
    return record


def order_key(record):
    return (record["created_at"], record["_seq"])


def sorted_records(records):
    return sorted(records, key=order_key)
