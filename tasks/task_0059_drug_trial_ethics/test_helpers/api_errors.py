"""Error IDs and HTTP status mapping (PRD §5).

After definition the mapping is registered with the framework so
validate_error() can auto-check HTTP status codes.
"""
from __future__ import annotations
from enum import Enum

from prd_bench_local_runner.testing.validators import (
    set_error_http_status_map,
)


class ApiErrorId(str, Enum):
    ERR_AUTH_MISSING = "ERR_AUTH_MISSING"
    ERR_AUTH_INVALID = "ERR_AUTH_INVALID"
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_MEMBER_RECUSED = "ERR_MEMBER_RECUSED"
    ERR_MEMBER_NOT_QUALIFIED = "ERR_MEMBER_NOT_QUALIFIED"
    ERR_AGENDA_LEAD_TIME_VIOLATION = "ERR_AGENDA_LEAD_TIME_VIOLATION"
    ERR_RECTIFICATION_EXPIRED = "ERR_RECTIFICATION_EXPIRED"
    ERR_CHECKLIST_INCOMPLETE = "ERR_CHECKLIST_INCOMPLETE"
    ERR_DUPLICATE_VOTE = "ERR_DUPLICATE_VOTE"
    ERR_QUORUM_NOT_MET = "ERR_QUORUM_NOT_MET"
    ERR_FIELD_VALIDATION = "ERR_FIELD_VALIDATION"
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"


HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_AUTH_MISSING: 401,
    ApiErrorId.ERR_AUTH_INVALID: 401,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_REFERENCE_NOT_FOUND: 404,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_MEMBER_RECUSED: 403,
    ApiErrorId.ERR_MEMBER_NOT_QUALIFIED: 422,
    ApiErrorId.ERR_AGENDA_LEAD_TIME_VIOLATION: 422,
    ApiErrorId.ERR_RECTIFICATION_EXPIRED: 409,
    ApiErrorId.ERR_CHECKLIST_INCOMPLETE: 422,
    ApiErrorId.ERR_DUPLICATE_VOTE: 409,
    ApiErrorId.ERR_QUORUM_NOT_MET: 422,
    ApiErrorId.ERR_FIELD_VALIDATION: 422,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
}


# Register with framework so validate_error() can cross-check HTTP statuses.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()}
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
