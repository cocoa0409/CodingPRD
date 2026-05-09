import uuid
import secrets
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


def fmt_ts(dt: datetime) -> str:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_ts(s: str) -> datetime:
    if s is None:
        return None
    if not isinstance(s, str):
        raise ValueError("timestamp must be a string")
    raw = s
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"invalid timestamp: {s}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_TWO_PLACES = Decimal("0.01")


def to_money(value) -> Decimal:
    if value is None:
        return None
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, (int,)):
        d = Decimal(value)
    elif isinstance(value, float):
        d = Decimal(str(value))
    elif isinstance(value, str):
        d = Decimal(value)
    else:
        raise ValueError(f"cannot convert {value!r} to money")
    return d.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def money_str(value):
    if value is None:
        return None
    d = to_money(value)
    return float(format(d, "f"))


def round_half_up(value: Decimal, places: int = 2) -> Decimal:
    q = Decimal(1).scaleb(-places)
    return value.quantize(q, rounding=ROUND_HALF_UP)
