"""Shared helpers: error type, response envelope, datetime + money utilities."""
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
ROLE_OPERATOR = "Operator"
ROLE_CUSTOMER = "Customer"
ROLE_GUIDE = "Guide"
ALL_ROLES = {ROLE_OPERATOR, ROLE_CUSTOMER, ROLE_GUIDE}


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, http_status, error_id, message=None):
        super().__init__(error_id)
        self.http_status = http_status
        self.error_id = error_id
        self.message = message or error_id


# ---------------------------------------------------------------------------
# IDs / timestamps
# ---------------------------------------------------------------------------
def new_uuid():
    return str(uuid.uuid4())


def gen_request_id():
    body = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + body


def wall_now():
    """Real server wall-clock time (used for created_at / updated_at)."""
    return datetime.utcnow()


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt is None:
        return None
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % millis


def parse_dt(value):
    """Parse an ISO 8601 instant into a naive-UTC datetime. Raises ValueError."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("not a datetime string")
    t = value.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        dt = None
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                    "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d"):
            try:
                dt = datetime.strptime(t, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            raise ValueError("unparseable datetime: %r" % value)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a Decimal to the nearest whole cent, ties going up. Returns int."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
