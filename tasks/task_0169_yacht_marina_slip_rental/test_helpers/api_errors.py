"""Error IDs and HTTP status mapping — PRD §5.

The mapping is registered with the framework at import time so
validate_error() auto-checks HTTP status codes without each test passing
them explicitly.
"""
from __future__ import annotations

from enum import Enum

from prd_bench_local_runner.testing.validators import (
    set_error_http_status_map,
)


class ApiErrorId(str, Enum):
    # Auth — PRD §2.1
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    # Existence — PRD §2.5
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    # State — PRD §3.4
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    # OCC — PRD §2.6
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"
    # Size-match business safety — PRD §3.4
    ERR_LOA_EXCEEDS_SLIP = "ERR_LOA_EXCEEDS_SLIP"
    ERR_BEAM_BUFFER_VIOLATION = "ERR_BEAM_BUFFER_VIOLATION"
    ERR_DRAFT_EXCEEDS_DEPTH = "ERR_DRAFT_EXCEEDS_DEPTH"
    # Insurance / liveaboard — PRD §3.4
    ERR_INSURANCE_LAPSED = "ERR_INSURANCE_LAPSED"
    ERR_LIVEABOARD_POLICY_VIOLATION = "ERR_LIVEABOARD_POLICY_VIOLATION"
    ERR_LIVEABOARD_QUOTA_EXCEEDED = "ERR_LIVEABOARD_QUOTA_EXCEEDED"
    # Temporal — PRD §3.4, §3.8
    ERR_SLIP_OCCUPIED = "ERR_SLIP_OCCUPIED"
    ERR_PUMP_OUT_CONFLICT = "ERR_PUMP_OUT_CONFLICT"
    ERR_INVALID_DATE_RANGE = "ERR_INVALID_DATE_RANGE"
    # Dependencies — PRD §3.2, §3.4
    ERR_HAS_DEPENDENCIES = "ERR_HAS_DEPENDENCIES"
    # Tow — PRD §3.8
    ERR_TOW_DEST_UNAVAILABLE = "ERR_TOW_DEST_UNAVAILABLE"
    # Generic — PRD §5
    ERR_BAD_REQUEST = "ERR_BAD_REQUEST"


# PRD §5 — Error Code Catalogue
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_LOA_EXCEEDS_SLIP: 422,
    ApiErrorId.ERR_BEAM_BUFFER_VIOLATION: 422,
    ApiErrorId.ERR_DRAFT_EXCEEDS_DEPTH: 422,
    ApiErrorId.ERR_INSURANCE_LAPSED: 422,
    ApiErrorId.ERR_LIVEABOARD_POLICY_VIOLATION: 422,
    ApiErrorId.ERR_LIVEABOARD_QUOTA_EXCEEDED: 409,
    ApiErrorId.ERR_SLIP_OCCUPIED: 409,
    ApiErrorId.ERR_PUMP_OUT_CONFLICT: 409,
    ApiErrorId.ERR_INVALID_DATE_RANGE: 422,
    ApiErrorId.ERR_HAS_DEPENDENCIES: 409,
    ApiErrorId.ERR_TOW_DEST_UNAVAILABLE: 422,
    ApiErrorId.ERR_BAD_REQUEST: 400,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
