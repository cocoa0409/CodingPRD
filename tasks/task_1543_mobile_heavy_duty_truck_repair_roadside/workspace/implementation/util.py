"""Time, decimal, and body-validation helpers."""
import re
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from errors import err_validation, err_invalid_enum

ISO_Z_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def now_wall_iso():
    """Wall-clock UTC timestamp with three fractional digits (meta/created_at)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_dt(dt):
    """Serialize an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def rhu(value):
    """Round a Decimal half-up to integer cents."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def month_window(now):
    """[start, end) aware datetimes of the logical clock's current calendar month."""
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


class Field:
    def __init__(self, name, kind, required=False, enum=None, nullable=False,
                 min_val=None, quarter_hour=False):
        self.name = name
        self.kind = kind  # string|int|number|bool|datetime|enum|enum_array|any
        self.required = required
        self.enum = enum
        self.nullable = nullable
        self.min_val = min_val
        self.quarter_hour = quarter_hour


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_body(data, fields):
    """Two-pass validation: shape (ERR_VALIDATION) then enum (ERR_INVALID_ENUM).

    Returns a dict of cleaned values (datetimes parsed). Missing optional fields
    are absent from the result; explicit null on a nullable field yields None.
    """
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err_validation("Request body must be a JSON object")
    allowed = {f.name for f in fields}
    for key in data:
        if key not in allowed:
            raise err_validation(f"Unknown field: {key}")
    out = {}
    # pass 1: presence + type + range
    for f in fields:
        present = f.name in data
        val = data.get(f.name)
        if not present or val is None:
            if present and val is None and f.nullable:
                out[f.name] = None
                continue
            if f.required:
                raise err_validation(f"Missing required field: {f.name}")
            continue
        if f.kind == "string":
            if not isinstance(val, str):
                raise err_validation(f"Field {f.name} must be a string")
            if f.required and not val.strip():
                raise err_validation(f"Field {f.name} must be non-blank")
            out[f.name] = val
        elif f.kind == "int":
            if not _is_int(val):
                raise err_validation(f"Field {f.name} must be an integer")
            if f.min_val is not None and val < f.min_val:
                raise err_validation(f"Field {f.name} must be >= {f.min_val}")
            out[f.name] = val
        elif f.kind == "number":
            if not _is_number(val):
                raise err_validation(f"Field {f.name} must be a number")
            if f.min_val is not None and val < f.min_val:
                raise err_validation(f"Field {f.name} must be >= {f.min_val}")
            if f.quarter_hour:
                cents = Decimal(str(val)) * 4
                if cents != cents.to_integral_value():
                    raise err_validation(
                        f"Field {f.name} must use quarter-hour granularity")
            out[f.name] = float(val)
        elif f.kind == "bool":
            if not isinstance(val, bool):
                raise err_validation(f"Field {f.name} must be a boolean")
            out[f.name] = val
        elif f.kind == "datetime":
            try:
                out[f.name] = parse_dt(val)
            except (ValueError, TypeError):
                raise err_validation(f"Field {f.name} must be an ISO 8601 datetime")
        elif f.kind == "enum":
            if not isinstance(val, str):
                raise err_validation(f"Field {f.name} must be a string enum")
            out[f.name] = val
        elif f.kind == "enum_array":
            if not isinstance(val, list) or any(not isinstance(x, str) for x in val):
                raise err_validation(f"Field {f.name} must be an array of strings")
            out[f.name] = val
        else:
            out[f.name] = val
    # pass 2: enum membership
    for f in fields:
        if f.name not in out or out[f.name] is None or f.enum is None:
            continue
        if f.kind == "enum":
            if out[f.name] not in f.enum:
                raise err_invalid_enum(
                    f"Field {f.name} must be one of {sorted(f.enum)}")
        elif f.kind == "enum_array":
            for x in out[f.name]:
                if x not in f.enum:
                    raise err_invalid_enum(
                        f"Field {f.name} must contain only {sorted(f.enum)}")
    return out


def parse_pagination(args):
    """limit/offset query params with defaults 10/0, bounds 1..100 / >=0."""
    limit_s = args.get("limit")
    offset_s = args.get("offset")
    if limit_s is None:
        limit = 10
    else:
        try:
            limit = int(limit_s)
        except (TypeError, ValueError):
            raise err_validation("limit must be an integer")
        if str(limit_s).strip() != str(limit):
            raise err_validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_validation("limit must be between 1 and 100")
    if offset_s is None:
        offset = 0
    else:
        try:
            offset = int(offset_s)
        except (TypeError, ValueError):
            raise err_validation("offset must be an integer")
        if str(offset_s).strip() != str(offset):
            raise err_validation("offset must be an integer")
        if offset < 0:
            raise err_validation("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + len(page)) < total
    return page, total, has_more
