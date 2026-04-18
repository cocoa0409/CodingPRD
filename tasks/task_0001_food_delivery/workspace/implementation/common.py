"""Common utilities: response envelope, error helpers, clock, id generation."""
import uuid
import secrets
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR
from flask import jsonify


# ========== Logical clock (virtual; can be advanced via /api/_clock/advance) ==========
class Clock:
    def __init__(self):
        self._offset_seconds = 0.0

    def now(self) -> datetime:
        return datetime.now(timezone.utc) + timedelta(seconds=self._offset_seconds)

    def advance(self, seconds: float):
        self._offset_seconds += float(seconds)

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
    # ISO 8601 UTC with three fractional digits, Z
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


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
    """Round Decimal/float to nearest integer using ROUND_HALF_UP."""
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_to_places(value, places: int) -> Decimal:
    """Round Decimal/float to given decimal places using ROUND_HALF_UP."""
    d = Decimal(str(value))
    quant = Decimal("1").scaleb(-places)  # 10^-places
    return d.quantize(quant, rounding=ROUND_HALF_UP)


def floor_to_int(value) -> int:
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_FLOOR))
