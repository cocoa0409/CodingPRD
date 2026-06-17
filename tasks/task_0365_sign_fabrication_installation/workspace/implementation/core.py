"""Core infrastructure: in-memory store, clock, response envelope, errors, time/money helpers.

Storage is in-memory only (plain dicts keyed by id). Nothing is seeded at startup.
"""
import math
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP


# ---------------------------------------------------------------------------
# In-memory store. One dict per entity collection, keyed by id (UUID string).
# Reset to empty on process start; never preloaded.
# ---------------------------------------------------------------------------
class Store(object):
    def __init__(self):
        self.sign_projects = {}
        self.art_proofs = {}
        self.estimates = {}
        self.site_surveys = {}
        self.permits = {}
        self.work_orders = {}
        self.install_jobs = {}
        self.crews = {}
        self.equipment = {}
        self.change_orders = {}
        self.warranty_claims = {}
        self.reorders = {}
        # Logical clock for deterministic time-dependent behavior. None => wall clock.
        self._clock = None
        # monotonic sequence so creation ordering / tie-breaks are stable even
        # when many entities share a millisecond timestamp.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        if self._clock is not None:
            return self._clock
        return datetime.now(timezone.utc)

    def set_clock(self, dt):
        self._clock = dt


db = Store()


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def iso_now(dt=None):
    """Return ISO 8601 UTC with exactly three fractional digits, 'Z' suffix."""
    if dt is None:
        dt = db.now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def parse_iso(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Returns None if the value is not a parseable datetime string.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Money / rounding helpers
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a numeric value half-up to the nearest whole integer (cents)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_div_area(width_in, height_in):
    """Billed area in whole square feet, rounded UP."""
    # Use exact arithmetic to avoid float edge cases at integer boundaries.
    area = Decimal(str(width_in)) * Decimal(str(height_in)) / Decimal("144")
    return int(math.ceil(area))


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super(ApiError, self).__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Catalogued errors (error_id -> http status). Messages are generic.
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_PROOF_ALREADY_APPROVED": 409,
    "ERR_REFERENCE_NOT_ELIGIBLE": 409,
    "ERR_ESTIMATE_EXPIRED": 409,
    "ERR_ESTIMATE_ALREADY_ACCEPTED": 409,
    "ERR_CLEARANCE_INSUFFICIENT": 409,
    "ERR_GROUND_BEARING_FAILED": 409,
    "ERR_PERMIT_NOT_REQUIRED": 409,
    "ERR_SURVEY_NOT_PASSED": 409,
    "ERR_PERMIT_NOT_APPROVED": 409,
    "ERR_EQUIPMENT_REQUIRED": 409,
    "ERR_EQUIPMENT_DOUBLE_BOOKED": 409,
    "ERR_CREW_DOUBLE_BOOKED": 409,
    "ERR_CREW_UNAVAILABLE": 409,
    "ERR_CREW_NOT_CERTIFIED": 409,
    "ERR_CHANGE_WINDOW_CLOSED": 409,
    "ERR_OUT_OF_WARRANTY": 409,
    "ERR_OPEN_CLAIM": 409,
    "ERR_SOURCE_NOT_CLOSED": 409,
    "ERR_STALE_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP.get(error_id, 400), message)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _request_id():
    rnd = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + rnd


def make_meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_now(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success_object(data, status=200):
    body = {
        "meta": make_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return body, status


def success_array(items, limit, offset, total_count, status=200):
    has_more = (offset + len(items)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {
        "meta": make_meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return body, status


def error_body(error_id, message):
    return {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
