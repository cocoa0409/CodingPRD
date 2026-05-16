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
    # Request / well-formedness — PRD §5
    ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"

    # Auth — PRD §2.1
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    ERR_FORBIDDEN_SAME_ACTOR = "ERR_FORBIDDEN_SAME_ACTOR"

    # Existence — PRD §2.5
    ERR_NOT_FOUND = "ERR_NOT_FOUND"

    # State — PRD §2.10 (validation priority 5)
    ERR_INVALID_STATE = "ERR_INVALID_STATE"

    # OCC — PRD §2.7
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"

    # Household completeness — PRD §3.3
    ERR_HOUSEHOLD_INCOMPLETE = "ERR_HOUSEHOLD_INCOMPLETE"

    # Appeal-window timeliness — PRD §3.6
    ERR_APPEAL_WINDOW_EXPIRED = "ERR_APPEAL_WINDOW_EXPIRED"

    # Appeal uniqueness — PRD §2.10
    ERR_APPEAL_ALREADY_EXISTS = "ERR_APPEAL_ALREADY_EXISTS"

    # Hearing — PRD §3.6
    ERR_HEARING_CONFLICT = "ERR_HEARING_CONFLICT"
    ERR_HEARING_NOT_DUE = "ERR_HEARING_NOT_DUE"

    # Enrollment overlap — PRD §3.4
    ERR_ENROLLMENT_OVERLAP = "ERR_ENROLLMENT_OVERLAP"

    # Fiscal — PRD §3.3
    ERR_NOT_ELIGIBLE = "ERR_NOT_ELIGIBLE"
    ERR_FPL_THRESHOLD_INVALID = "ERR_FPL_THRESHOLD_INVALID"


# PRD §5 Error Code Catalogue — exact HTTP status code mapping.
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_INVALID_REQUEST: 400,
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_FORBIDDEN_SAME_ACTOR: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_HOUSEHOLD_INCOMPLETE: 409,
    ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED: 409,
    ApiErrorId.ERR_APPEAL_ALREADY_EXISTS: 409,
    ApiErrorId.ERR_HEARING_CONFLICT: 409,
    ApiErrorId.ERR_HEARING_NOT_DUE: 409,
    ApiErrorId.ERR_ENROLLMENT_OVERLAP: 409,
    ApiErrorId.ERR_NOT_ELIGIBLE: 422,
    ApiErrorId.ERR_FPL_THRESHOLD_INVALID: 422,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
