"""Common utilities: response envelope, error helpers, logical clock, id generation."""
import uuid
import secrets
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR
from flask import jsonify


# ========== Logical clock (virtual; advanced via /_clock/advance) ==========
class Clock:
    def __init__(self):
        # Logical clock that floors at wall time. PRD §2.14 says /_clock/advance
        # pushes the logical clock to a target instant; it does not forbid the
        # clock from naturally tracking wall time in the interim. Auto-tracking
        # wall time as the floor lets a freshly-rebooted server begin accepting
        # "+48h from now" bookings without waiting for an explicit advance.
        self._offset = 0.0  # seconds the clock has been pushed beyond wall time

    def now(self) -> datetime:
        wall = datetime.now(timezone.utc).replace(microsecond=0)
        return wall + timedelta(seconds=self._offset)

    def advance_to(self, target: datetime):
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        else:
            target = target.astimezone(timezone.utc)
        current = self.now()
        if target > current:
            self._offset += (target - current).total_seconds()

    def set_now(self, target: datetime):
        # Test override only.
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        else:
            target = target.astimezone(timezone.utc)
        wall = datetime.now(timezone.utc).replace(microsecond=0)
        self._offset = (target - wall).total_seconds()

    def reset(self):
        """Reset the offset so the clock tracks wall time exactly."""
        self._offset = 0.0


CLOCK = Clock()


def iso_now() -> str:
    return format_iso(CLOCK.now())


def format_iso(dt: datetime) -> str:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s: str) -> datetime:
    if s is None:
        return None
    if not isinstance(s, str):
        raise ValueError("not a string timestamp")
    # Accept "...Z" and "+00:00"
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def gen_uuid() -> str:
    return str(uuid.uuid4())


def gen_request_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


# ========== Response envelope ==========
def make_meta(extra: dict = None) -> dict:
    meta = {
        "api_request_id": gen_request_id(),
        "api_request_timestamp": iso_now(),
    }
    if extra:
        meta.update(extra)
    return meta


def success_object(data, status_code: int = 200):
    body = {
        "meta": make_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status_code


def success_array(items, limit: int, offset: int, total_count: int, status_code: int = 200):
    meta = make_meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    })
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status_code


def error_response(error_id: str, http_status: int, message: str = None):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message or error_id,
        },
    }
    return jsonify(body), http_status


# ========== Custom error exception ==========
class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = None):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


# ========== Monetary helpers ==========
def round_half_up_to_int(value) -> int:
    """Round Decimal/float/int to nearest integer using ROUND_HALF_UP."""
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_to_int(value) -> int:
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_CEILING))


def floor_to_int(value) -> int:
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_FLOOR))
