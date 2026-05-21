"""Error IDs and HTTP status mapping (PRD §5 Error Code Catalogue).

After definition, the mapping is registered with the framework so
validate_error() can auto-check HTTP status codes without each test
passing them explicitly.
"""
from __future__ import annotations

from enum import Enum

from prd_bench_local_runner.testing.validators import (
    set_error_http_status_map,
)


class ApiErrorId(str, Enum):
    # --- Request shape / auth --- PRD §2.1, §5
    ERR_AUTH_REQUIRED = "ERR_AUTH_REQUIRED"
    ERR_AUTH_INVALID_ROLE = "ERR_AUTH_INVALID_ROLE"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"

    # --- Existence --- PRD §2.6, §5
    ERR_RESOURCE_NOT_FOUND = "ERR_RESOURCE_NOT_FOUND"
    ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"

    # --- Validation / request body --- PRD §2.8, §5
    ERR_VALIDATION_FAILED = "ERR_VALIDATION_FAILED"

    # --- State preconditions --- PRD §2.8, §3.x, §5
    ERR_INVALID_ASSIGNMENT_STATE = "ERR_INVALID_ASSIGNMENT_STATE"
    ERR_PAIRING_INVALID_STATE = "ERR_PAIRING_INVALID_STATE"
    ERR_INVALID_TRADE_STATE = "ERR_INVALID_TRADE_STATE"
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"

    # --- Bid / award races --- PRD §2.11, §3.3, §5
    ERR_BID_WINDOW_CLOSED = "ERR_BID_WINDOW_CLOSED"
    ERR_BID_WINDOW_ALREADY_AWARDED = "ERR_BID_WINDOW_ALREADY_AWARDED"
    ERR_DUPLICATE_BID_PREFERENCE = "ERR_DUPLICATE_BID_PREFERENCE"
    ERR_SLOT_ALREADY_COVERED = "ERR_SLOT_ALREADY_COVERED"

    # --- FAA business safety --- PRD §3.5, §5
    ERR_FAA_CREW_REST_VIOLATION = "ERR_FAA_CREW_REST_VIOLATION"
    ERR_FAA_DUTY_VIOLATION = "ERR_FAA_DUTY_VIOLATION"

    # --- Trade / union --- PRD §3.8, §5
    ERR_TRADE_RULE_VIOLATION = "ERR_TRADE_RULE_VIOLATION"

    # --- Temporal / window --- PRD §3.2, §3.4, §5
    ERR_RESERVE_OUTSIDE_WINDOW = "ERR_RESERVE_OUTSIDE_WINDOW"
    ERR_NO_RESERVE_AVAILABLE = "ERR_NO_RESERVE_AVAILABLE"
    ERR_BID_TOO_LATE = "ERR_BID_TOO_LATE"

    # --- Pairing/flight-leg structure --- PRD §3.1, §5
    ERR_PAIRING_INTERNAL_OVERLAP = "ERR_PAIRING_INTERNAL_OVERLAP"
    ERR_FLIGHT_LEG_INVALID = "ERR_FLIGHT_LEG_INVALID"

    # --- Crew availability --- PRD §3.1, §5
    ERR_CREW_NOT_AVAILABLE = "ERR_CREW_NOT_AVAILABLE"


# PRD §5 Error Code Catalogue — HTTP status per error_id.
HTTP_STATUS_CODES: dict = {
    # 400
    ApiErrorId.ERR_VALIDATION_FAILED: 400,
    # 401
    ApiErrorId.ERR_AUTH_REQUIRED: 401,
    ApiErrorId.ERR_AUTH_INVALID_ROLE: 401,
    # 403
    ApiErrorId.ERR_FORBIDDEN: 403,
    # 404
    ApiErrorId.ERR_RESOURCE_NOT_FOUND: 404,
    ApiErrorId.ERR_REFERENCE_NOT_FOUND: 404,
    # 409
    ApiErrorId.ERR_INVALID_ASSIGNMENT_STATE: 409,
    ApiErrorId.ERR_PAIRING_INVALID_STATE: 409,
    ApiErrorId.ERR_INVALID_TRADE_STATE: 409,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_BID_WINDOW_CLOSED: 409,
    ApiErrorId.ERR_BID_WINDOW_ALREADY_AWARDED: 409,
    ApiErrorId.ERR_DUPLICATE_BID_PREFERENCE: 409,
    ApiErrorId.ERR_SLOT_ALREADY_COVERED: 409,
    # 422
    ApiErrorId.ERR_FAA_CREW_REST_VIOLATION: 422,
    ApiErrorId.ERR_FAA_DUTY_VIOLATION: 422,
    ApiErrorId.ERR_TRADE_RULE_VIOLATION: 422,
    ApiErrorId.ERR_RESERVE_OUTSIDE_WINDOW: 422,
    ApiErrorId.ERR_NO_RESERVE_AVAILABLE: 422,
    ApiErrorId.ERR_BID_TOO_LATE: 422,
    ApiErrorId.ERR_PAIRING_INTERNAL_OVERLAP: 422,
    ApiErrorId.ERR_FLIGHT_LEG_INVALID: 422,
    ApiErrorId.ERR_CREW_NOT_AVAILABLE: 422,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
