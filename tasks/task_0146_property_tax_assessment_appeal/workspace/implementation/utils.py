"""Shared utility helpers — UUIDs, timestamps, rounding, parsing."""

import re
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def new_uuid() -> str:
    return str(uuid.uuid4())


def round_half_up(value, places: int = 2) -> Decimal:
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    q = Decimal(10) ** (-places)
    return value.quantize(q, rounding=ROUND_HALF_UP)


def parse_iso_datetime(s: str) -> datetime:
    if not isinstance(s, str) or not ISO_RE.match(s):
        raise ValueError("invalid ISO 8601 datetime")
    # Normalise trailing Z to +00:00
    text = s
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_date(s: str) -> date:
    if not isinstance(s, str) or not DATE_RE.match(s):
        raise ValueError("invalid ISO date")
    return date.fromisoformat(s)


def to_decimal(value, allow_none: bool = False) -> Decimal:
    if value is None:
        if allow_none:
            return None
        raise ValueError("number required")
    if isinstance(value, bool):
        raise ValueError("boolean is not a number")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except Exception:
            raise ValueError("invalid number")
    raise ValueError("invalid number")


def age_on(date_of_birth: date, on_date: date) -> int:
    years = on_date.year - date_of_birth.year
    if (on_date.month, on_date.day) < (date_of_birth.month, date_of_birth.day):
        years -= 1
    return years
