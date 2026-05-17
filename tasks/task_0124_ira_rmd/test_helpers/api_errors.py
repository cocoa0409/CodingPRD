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
    # Auth — PRD §2.1
    ERR_AUTH_MISSING = "ERR_AUTH_MISSING"
    ERR_AUTH_INVALID_ROLE = "ERR_AUTH_INVALID_ROLE"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"

    # Existence — PRD §2.6
    ERR_NOT_FOUND = "ERR_NOT_FOUND"

    # Schema — PRD §2.7 / §5
    ERR_VALIDATION = "ERR_VALIDATION"

    # Account / participant posture — PRD §2.7, §3.2
    ERR_ACCOUNT_FROZEN = "ERR_ACCOUNT_FROZEN"
    ERR_ACCOUNT_CLOSED = "ERR_ACCOUNT_CLOSED"
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_PARTICIPANT_DECEASED = "ERR_PARTICIPANT_DECEASED"

    # Beneficiary / SECURE Act — PRD §3.5, §3.6
    ERR_INHERITED_CLAIM_FORFEITED = "ERR_INHERITED_CLAIM_FORFEITED"
    ERR_SECURE_DEADLINE_EXPIRED = "ERR_SECURE_DEADLINE_EXPIRED"

    # Conversion business rules — PRD §3.7
    ERR_INVALID_CONVERSION_PAIR = "ERR_INVALID_CONVERSION_PAIR"
    ERR_CROSS_PARTICIPANT_CONVERSION = "ERR_CROSS_PARTICIPANT_CONVERSION"
    ERR_SEGREGATION_VIOLATION = "ERR_SEGREGATION_VIOLATION"

    # Contribution / distribution fiscal — PRD §3.3, §3.4, §3.5
    ERR_CONTRIBUTION_CAP_EXCEEDED = "ERR_CONTRIBUTION_CAP_EXCEEDED"
    ERR_CATCHUP_AGE_INELIGIBLE = "ERR_CATCHUP_AGE_INELIGIBLE"
    ERR_INSUFFICIENT_BALANCE = "ERR_INSUFFICIENT_BALANCE"
    ERR_RMD_AMOUNT_MISMATCH = "ERR_RMD_AMOUNT_MISMATCH"
    ERR_BACKDOOR_PRECONDITION_VIOLATED = "ERR_BACKDOOR_PRECONDITION_VIOLATED"

    # RMD temporal — PRD §3.5
    ERR_RMD_PERIOD_CLOSED = "ERR_RMD_PERIOD_CLOSED"
    ERR_RMD_ALREADY_TAKEN = "ERR_RMD_ALREADY_TAKEN"

    # OCC — PRD §2.5
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"


# PRD §5 Error Code Catalogue — http status per error_id.
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_AUTH_MISSING: 401,
    ApiErrorId.ERR_AUTH_INVALID_ROLE: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_VALIDATION: 400,
    ApiErrorId.ERR_ACCOUNT_FROZEN: 409,
    ApiErrorId.ERR_ACCOUNT_CLOSED: 409,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_PARTICIPANT_DECEASED: 409,
    ApiErrorId.ERR_INHERITED_CLAIM_FORFEITED: 409,
    ApiErrorId.ERR_SECURE_DEADLINE_EXPIRED: 422,
    ApiErrorId.ERR_INVALID_CONVERSION_PAIR: 422,
    ApiErrorId.ERR_CROSS_PARTICIPANT_CONVERSION: 422,
    ApiErrorId.ERR_SEGREGATION_VIOLATION: 403,
    ApiErrorId.ERR_CONTRIBUTION_CAP_EXCEEDED: 422,
    ApiErrorId.ERR_CATCHUP_AGE_INELIGIBLE: 422,
    ApiErrorId.ERR_INSUFFICIENT_BALANCE: 422,
    ApiErrorId.ERR_RMD_AMOUNT_MISMATCH: 422,
    ApiErrorId.ERR_BACKDOOR_PRECONDITION_VIOLATED: 422,
    ApiErrorId.ERR_RMD_PERIOD_CLOSED: 409,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_RMD_ALREADY_TAKEN: 409,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
