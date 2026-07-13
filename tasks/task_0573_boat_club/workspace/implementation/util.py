"""Utility helpers: error catalog/class, datetime parse/format, rounding, ids."""
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


# --- Error catalog: error_id -> HTTP status (PRD section 5 / scaffold 1.6) ---
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FORBIDDEN": 403,
    "ERR_VALIDATION": 400,
    "ERR_DOCK_NOT_FOUND": 404,
    "ERR_TIER_NOT_FOUND": 404,
    "ERR_BOAT_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_RESERVATION_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_DAMAGE_REPORT_NOT_FOUND": 404,
    "ERR_FEE_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_MEMBER_NOT_ACTIVE": 409,
    "ERR_BOAT_NOT_AVAILABLE": 409,
    "ERR_FEE_NOT_ASSESSED": 409,
    "ERR_CERT_INSUFFICIENT": 422,
    "ERR_ORIENTATION_REQUIRED": 422,
    "ERR_BOOKING_WINDOW": 409,
    "ERR_MEMBER_SCHEDULE_CONFLICT": 409,
    "ERR_NO_BOAT_AVAILABLE": 409,
    "ERR_RECIPROCAL_NOT_ALLOWED": 422,
    "ERR_MAX_ACTIVE_RESERVATIONS": 409,
    "ERR_WEEKLY_QUOTA_EXCEEDED": 409,
    "ERR_DUPLICATE_ENROLLMENT": 409,
    "ERR_SESSION_FULL": 409,
    "ERR_OUTSTANDING_FEES": 402,
    "ERR_STALE_VERSION": 412,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.status = ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id


def parse_dt(value):
    """Parse an ISO 8601 string into a tz-aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    t = value.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits and Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_dt(datetime.now(timezone.utc))


def rhu(dec_value):
    """Round a Decimal (or number) half-up to an integer number of cents."""
    return int(Decimal(dec_value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def gen_request_id():
    return "req_" + "".join(
        random.choices(string.ascii_letters + string.digits, k=20)
    )
