"""Shared helpers: auth extraction, RBAC, pagination, body parsing, time/money math."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import err

VALID_ROLES = {"PlatformAdmin", "SupplierUser", "PhysicianUser", "PayerReviewer"}


# ---------------------------------------------------------------------------
# Auth & RBAC (PRD 2.1; SCAFFOLD validations priority 1-2)
# ---------------------------------------------------------------------------
def require_auth():
    """Priority 1: X-User-Role and X-User-ID headers present and role valid.

    Returns (user_id, role) or raises ERR_UNAUTHENTICATED (401).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid X-User-ID / X-User-Role header")
    return user_id, role


def require_role(role, allowed):
    """Priority 2: acting role permitted for this operation, else ERR_FORBIDDEN (403)."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role %s not permitted for this operation" % role)


# ---------------------------------------------------------------------------
# Body parsing
# ---------------------------------------------------------------------------
def get_body():
    """Return the JSON body as a dict; treat empty/None as {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3; envelope pagination_defaults limit=10 min=1 max=100 offset=0)
# ---------------------------------------------------------------------------
def parse_pagination():
    """Return (limit, offset). Out-of-range/malformed -> ERR_INVALID_REQUEST (400)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")

    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ascending (PRD 2.3) then apply offset/limit.

    Returns (page, total_count, has_more). Stable secondary sort on id so equal
    created_at timestamps (same logical clock instant) keep insertion-like order
    via a deterministic tiebreak.
    """
    ordered = sorted(records, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    has_more = (offset + len(page)) < total
    return page, total, has_more


# ---------------------------------------------------------------------------
# Time math
# ---------------------------------------------------------------------------
def parse_iso8601(value):
    """Parse an ISO 8601 timestamp into a tz-aware UTC datetime.

    Accepts a trailing Z or an explicit offset. Returns None on failure.
    """
    if not isinstance(value, str) or not value:
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_date(value):
    """Parse a YYYY-MM-DD date string into a date. Returns None on failure."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def to_iso8601(dt):
    """Format a tz-aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def add_months(dt, months):
    """Add a whole number of calendar months to a datetime (clamping day)."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    # Clamp the day to the last valid day of the target month.
    day = dt.day
    while True:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1
            if day < 1:
                raise


def whole_days_between(earlier, later):
    """Floor of elapsed duration in whole days between two datetimes."""
    delta = later - earlier
    return delta.days  # timedelta.days is the floor of total days for positive deltas


def add_days(dt, days):
    return dt + timedelta(days=days)


# ---------------------------------------------------------------------------
# Money / rounding (PRD 2.6: half up, away from zero on .5)
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a Decimal/number to the nearest whole cent, half away from zero."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
