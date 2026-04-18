from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP
import re

from errors import raise_error, ERR_VERSION_CONFLICT


ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_iso(s: str) -> datetime | None:
    if not isinstance(s, str):
        return None
    try:
        # Accept .sss precision as well as no fractional
        dt = datetime.strptime(s.replace("Z", "+00:00")[:-6] if s.endswith("+00:00") else s.replace("Z", "+00:00"),
                               "%Y-%m-%dT%H:%M:%S.%f%z") if "." in s else datetime.strptime(
            s.replace("Z", "+00:00"), "%Y-%m-%dT%H:%M:%S%z")
        return dt.astimezone(timezone.utc)
    except Exception:
        # Try more lenient
        try:
            clean = s
            if clean.endswith("Z"):
                clean = clean[:-1] + "+00:00"
            dt = datetime.fromisoformat(clean)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None


def parse_date(s: str) -> date | None:
    if not isinstance(s, str):
        return None
    if not DATE_RE.match(s):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def now_iso_string(dt: datetime) -> str:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = int(dt.microsecond / 1000)
    return f"{s}.{ms:03d}Z"


def round_half_up(x) -> int:
    """Round a Decimal or float to the nearest integer using ROUND_HALF_UP."""
    if isinstance(x, int):
        return x
    d = Decimal(str(x)) if not isinstance(x, Decimal) else x
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def bump(entity: dict, clock: datetime):
    entity["updated_at"] = now_iso_string(clock)
    entity["version"] = entity.get("version", 0) + 1


def check_version(entity: dict, supplied):
    if supplied is None:
        return
    try:
        supplied_int = int(supplied)
    except Exception:
        raise_error(ERR_VERSION_CONFLICT, "Invalid version value")
    if entity.get("version") != supplied_int:
        raise_error(ERR_VERSION_CONFLICT, "Version mismatch")


def is_minute_aligned(dt: datetime) -> bool:
    return dt.second == 0 and dt.microsecond == 0


def fractional_hours(start: datetime, end: datetime) -> Decimal:
    seconds = Decimal(str((end - start).total_seconds()))
    return seconds / Decimal("3600")


def ceil_to_half_hour_units(hours: Decimal) -> int:
    """Return the number of 30-minute units needed to cover 'hours'."""
    if hours <= 0:
        return 0
    units = hours * Decimal(2)
    # ceil
    rounded = units.to_integral_value(rounding="ROUND_CEILING")
    return int(rounded)


def ceil_to_days(hours: Decimal, hours_per_day: int = 8) -> int:
    if hours <= 0:
        return 0
    days = hours / Decimal(hours_per_day)
    rounded = days.to_integral_value(rounding="ROUND_CEILING")
    return int(rounded)


def ceil_to_blocks(hours: Decimal, hours_per_block: int = 4) -> int:
    if hours <= 0:
        return 0
    blocks = hours / Decimal(hours_per_block)
    rounded = blocks.to_integral_value(rounding="ROUND_CEILING")
    return int(rounded)


def add_common_fields(entity: dict, clock: datetime, new_id: str):
    entity["id"] = new_id
    entity["created_at"] = now_iso_string(clock)
    entity["updated_at"] = now_iso_string(clock)
    entity["version"] = 1
