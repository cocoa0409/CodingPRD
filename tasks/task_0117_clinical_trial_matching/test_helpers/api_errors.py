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
    # Auth / RBAC — PRD §2.1
    ERR_AUTH_REQUIRED = "ERR_AUTH_REQUIRED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    ERR_SOD_VIOLATION = "ERR_SOD_VIOLATION"

    # Existence — PRD §2.7
    ERR_NOT_FOUND = "ERR_NOT_FOUND"

    # State — PRD §2.8 / §3.3 / §3.5
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_IRB_EXPIRED = "ERR_IRB_EXPIRED"

    # Randomization / consent / enrollment — PRD §3.1 / §3.5 / §2.10
    ERR_RANDOMIZATION_MISCONFIGURED = "ERR_RANDOMIZATION_MISCONFIGURED"
    ERR_CONSENT_VERSION_STALE = "ERR_CONSENT_VERSION_STALE"
    ERR_TRIAL_FULL = "ERR_TRIAL_FULL"
    ERR_STRATUM_KEY_MISSING = "ERR_STRATUM_KEY_MISSING"

    # Safety / temporal — PRD §3.6 / §3.7 / §2.9
    ERR_AE_BLOCKING = "ERR_AE_BLOCKING"
    ERR_DRAW_OUTSIDE_WINDOW = "ERR_DRAW_OUTSIDE_WINDOW"
    ERR_WINDOW_NOT_YET_PASSED = "ERR_WINDOW_NOT_YET_PASSED"

    # Uniqueness / referential — PRD §3.1 / §3.6 / §3.7
    ERR_DUPLICATE_VISIT_SEQUENCE = "ERR_DUPLICATE_VISIT_SEQUENCE"
    ERR_DUPLICATE_PROTOCOL_CODE = "ERR_DUPLICATE_PROTOCOL_CODE"
    ERR_CROSS_PARTICIPANT_REFERENCE = "ERR_CROSS_PARTICIPANT_REFERENCE"

    # OCC / input schema — PRD §2.6 / §2.8
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"
    ERR_INVALID_INPUT = "ERR_INVALID_INPUT"

    # Defensive — PRD §3.5
    ERR_NO_ARMS_DEFINED = "ERR_NO_ARMS_DEFINED"


# PRD §5 Error Code Catalogue.
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_AUTH_REQUIRED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_SOD_VIOLATION: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_IRB_EXPIRED: 409,
    ApiErrorId.ERR_RANDOMIZATION_MISCONFIGURED: 422,
    ApiErrorId.ERR_CONSENT_VERSION_STALE: 409,
    ApiErrorId.ERR_TRIAL_FULL: 409,
    ApiErrorId.ERR_STRATUM_KEY_MISSING: 422,
    ApiErrorId.ERR_AE_BLOCKING: 409,
    ApiErrorId.ERR_DRAW_OUTSIDE_WINDOW: 409,
    ApiErrorId.ERR_WINDOW_NOT_YET_PASSED: 409,
    ApiErrorId.ERR_DUPLICATE_VISIT_SEQUENCE: 409,
    ApiErrorId.ERR_DUPLICATE_PROTOCOL_CODE: 409,
    ApiErrorId.ERR_CROSS_PARTICIPANT_REFERENCE: 422,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_INVALID_INPUT: 422,
    ApiErrorId.ERR_NO_ARMS_DEFINED: 422,
}


# Register with the framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
