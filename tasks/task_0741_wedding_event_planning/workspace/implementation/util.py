"""Utility helpers: errors, datetime parsing/formatting, rounding, ids."""
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


# --- Error catalog: error_id -> HTTP status (from PRD section 5) ---
ERROR_STATUS = {
    # auth / authz / ownership
    "ERR_MISSING_OR_INVALID_HEADERS": 400,
    "ERR_UNAUTHORIZED": 403,
    "ERR_OWNERSHIP_VIOLATION": 403,
    # not found
    "ERR_EVENT_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_VENDOR_NOT_FOUND": 404,
    "ERR_COI_NOT_FOUND": 404,
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_PAYMENT_NOT_FOUND": 404,
    "ERR_TIMELINE_BLOCK_NOT_FOUND": 404,
    "ERR_GUEST_NOT_FOUND": 404,
    "ERR_TABLE_NOT_FOUND": 404,
    "ERR_SEAT_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_STAFF_MEMBER_NOT_FOUND": 404,
    "ERR_STAFF_ASSIGNMENT_NOT_FOUND": 404,
    # input
    "ERR_VALIDATION": 400,
    "ERR_INVALID_INTERVAL": 422,
    "ERR_SEAT_EVENT_MISMATCH": 400,
    # OCC
    "ERR_STALE_EVENT_VERSION": 412,
    # state
    "ERR_EVENT_NOT_DRAFT": 409,
    "ERR_EVENT_NOT_BOOKING": 409,
    "ERR_EVENT_NOT_CANCELLABLE": 409,
    "ERR_EVENT_DATE_NOT_REACHED": 409,
    "ERR_UNRESOLVED_BOOKINGS": 409,
    "ERR_CONTRACT_NOT_DRAFT": 409,
    "ERR_CONTRACT_NOT_SENT": 409,
    "ERR_CONTRACT_NOT_SIGNED": 409,
    "ERR_CONTRACT_NOT_COUNTERSIGNED": 409,
    "ERR_BOOKING_NOT_PROPOSED": 409,
    "ERR_BOOKING_NOT_CANCELLABLE": 409,
    "ERR_PAYMENT_NOT_SCHEDULED": 409,
    "ERR_GUEST_NOT_ACCEPTED": 409,
    "ERR_COI_NOT_PENDING": 409,
    # business
    "ERR_COI_EXPIRED": 422,
    "ERR_COI_NOT_VERIFIED": 403,
    "ERR_TIMELINE_OVERLAP": 409,
    "ERR_STAFF_DOUBLE_BOOKED": 409,
    "ERR_GUEST_ALREADY_SEATED": 409,
    "ERR_TABLE_CAPACITY_EXCEEDED": 409,
    "ERR_BUDGET_EXCEEDED": 402,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.status = ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id


# --- datetime helpers (all internal datetimes are tz-aware UTC) ---
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


# --- money ---
def rhu(dec_value):
    """Round a Decimal half-up to an integer."""
    return int(Decimal(dec_value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def gen_request_id():
    return "req_" + "".join(
        random.choices(string.ascii_letters + string.digits, k=20)
    )
