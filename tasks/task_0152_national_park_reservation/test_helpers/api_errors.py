"""Error IDs and HTTP status mapping — PRD §5 Error Code Catalogue.

After definition, the mapping is registered with the framework so
validate_error() auto-checks HTTP status codes without each test
passing them explicitly.
"""
from __future__ import annotations

from enum import Enum

from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    # PRD §2.1, §2.12 — auth
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    # PRD §2.6, §2.12 — existence
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    # PRD §2.12 — generic validation
    ERR_VALIDATION = "ERR_VALIDATION"
    # PRD §2.5, §2.11 — concurrency
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"
    # PRD §2.7, §2.11, §2.12 — state
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    # PRD §2.7 — park posture
    ERR_PARK_FROZEN = "ERR_PARK_FROZEN"
    ERR_PARK_RESTRICTED = "ERR_PARK_RESTRICTED"
    # PRD §3.3 — timed-entry
    ERR_OUT_OF_BOOKING_WINDOW = "ERR_OUT_OF_BOOKING_WINDOW"
    ERR_WINDOW_MISALIGNED = "ERR_WINDOW_MISALIGNED"
    ERR_TIMED_ENTRY_FULL = "ERR_TIMED_ENTRY_FULL"
    # PRD §3.4 — campground
    ERR_CAMPGROUND_FULL = "ERR_CAMPGROUND_FULL"
    # PRD §3.7 — backcountry
    ERR_BACKCOUNTRY_FULL = "ERR_BACKCOUNTRY_FULL"
    ERR_RANGER_BUFFER_VIOLATION = "ERR_RANGER_BUFFER_VIOLATION"
    # PRD §3.1, §3.3 — pass referential
    ERR_PASS_INVALID = "ERR_PASS_INVALID"
    # PRD §3.4, §3.6 — party-size
    ERR_PARTY_SIZE_INVALID = "ERR_PARTY_SIZE_INVALID"
    # PRD §3.4 — campground stay limits
    ERR_STAY_TOO_LONG = "ERR_STAY_TOO_LONG"
    # PRD §2.8, §3.3, §3.4, §3.6, §3.7 — fiscal
    ERR_INSUFFICIENT_FUNDS = "ERR_INSUFFICIENT_FUNDS"
    # PRD §3.6 — lottery
    ERR_LOTTERY_CLOSED = "ERR_LOTTERY_CLOSED"
    ERR_LOTTERY_ALREADY_DRAWN = "ERR_LOTTERY_ALREADY_DRAWN"
    # PRD §2.12, §3.1, §3.4, §3.6 — strike limit
    ERR_STRIKE_LIMIT_REACHED = "ERR_STRIKE_LIMIT_REACHED"
    # PRD §3.6 — award expiry
    ERR_AWARD_EXPIRED = "ERR_AWARD_EXPIRED"


# PRD §5 — Error Code Catalogue (HTTP status mapping).
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_VALIDATION: 422,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_PARK_FROZEN: 409,
    ApiErrorId.ERR_PARK_RESTRICTED: 409,
    ApiErrorId.ERR_OUT_OF_BOOKING_WINDOW: 422,
    ApiErrorId.ERR_WINDOW_MISALIGNED: 422,
    ApiErrorId.ERR_TIMED_ENTRY_FULL: 409,
    ApiErrorId.ERR_CAMPGROUND_FULL: 409,
    ApiErrorId.ERR_BACKCOUNTRY_FULL: 409,
    ApiErrorId.ERR_RANGER_BUFFER_VIOLATION: 409,
    ApiErrorId.ERR_PASS_INVALID: 422,
    ApiErrorId.ERR_PARTY_SIZE_INVALID: 422,
    ApiErrorId.ERR_STAY_TOO_LONG: 422,
    ApiErrorId.ERR_INSUFFICIENT_FUNDS: 402,
    ApiErrorId.ERR_LOTTERY_CLOSED: 422,
    ApiErrorId.ERR_LOTTERY_ALREADY_DRAWN: 409,
    ApiErrorId.ERR_STRIKE_LIMIT_REACHED: 422,
    ApiErrorId.ERR_AWARD_EXPIRED: 409,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map({k.value: v for k, v in HTTP_STATUS_CODES.items()})


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
