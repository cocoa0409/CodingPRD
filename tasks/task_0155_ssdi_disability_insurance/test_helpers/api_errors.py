"""Error IDs and HTTP status mapping — PRD §5 Error Code Catalogue.

The mapping is registered with the framework so validate_error()
auto-checks HTTP status codes without each test passing them
explicitly.
"""
from __future__ import annotations

from enum import Enum

from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    # PRD §2.1 — auth
    ERR_AUTH_REQUIRED = "ERR_AUTH_REQUIRED"
    ERR_INVALID_ROLE = "ERR_INVALID_ROLE"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
    # PRD §2.7 — existence
    ERR_CLAIMANT_NOT_FOUND = "ERR_CLAIMANT_NOT_FOUND"
    ERR_APPLICATION_NOT_FOUND = "ERR_APPLICATION_NOT_FOUND"
    ERR_RESOURCE_NOT_FOUND = "ERR_RESOURCE_NOT_FOUND"
    # PRD §2.9 — state and concurrency
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_VERSION_MISMATCH = "ERR_VERSION_MISMATCH"
    # PRD §3.7 — hearing
    ERR_HEARING_SLOT_CONFLICT = "ERR_HEARING_SLOT_CONFLICT"
    ERR_APPLICATION_ALREADY_SCHEDULED = "ERR_APPLICATION_ALREADY_SCHEDULED"
    ERR_APPEAL_WINDOW_EXPIRED = "ERR_APPEAL_WINDOW_EXPIRED"
    ERR_HEARING_NOT_REACHED = "ERR_HEARING_NOT_REACHED"
    ERR_HEARING_NOT_HELD = "ERR_HEARING_NOT_HELD"
    # PRD §3 — domain constraint
    ERR_QC_INSUFFICIENT = "ERR_QC_INSUFFICIENT"
    ERR_EVIDENCE_INSUFFICIENT = "ERR_EVIDENCE_INSUFFICIENT"
    ERR_AOD_AFTER_FILING = "ERR_AOD_AFTER_FILING"
    ERR_CHILD_INELIGIBLE = "ERR_CHILD_INELIGIBLE"
    ERR_SSI_RESOURCES_EXCEEDED = "ERR_SSI_RESOURCES_EXCEEDED"
    ERR_CDR_NOT_DUE = "ERR_CDR_NOT_DUE"
    # PRD §2.3 — pagination
    ERR_INVALID_PAGINATION = "ERR_INVALID_PAGINATION"
    # PRD §2.9 — body shape catchall
    ERR_BAD_REQUEST = "ERR_BAD_REQUEST"


# PRD §5 — Error Code Catalogue (HTTP status mapping).
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_AUTH_REQUIRED: 401,
    ApiErrorId.ERR_INVALID_ROLE: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_SEGREGATION_OF_DUTIES: 403,
    ApiErrorId.ERR_CLAIMANT_NOT_FOUND: 404,
    ApiErrorId.ERR_APPLICATION_NOT_FOUND: 404,
    ApiErrorId.ERR_RESOURCE_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_VERSION_MISMATCH: 409,
    ApiErrorId.ERR_HEARING_SLOT_CONFLICT: 409,
    ApiErrorId.ERR_APPLICATION_ALREADY_SCHEDULED: 409,
    ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED: 409,
    ApiErrorId.ERR_HEARING_NOT_REACHED: 422,
    ApiErrorId.ERR_HEARING_NOT_HELD: 422,
    ApiErrorId.ERR_QC_INSUFFICIENT: 422,
    ApiErrorId.ERR_EVIDENCE_INSUFFICIENT: 422,
    ApiErrorId.ERR_AOD_AFTER_FILING: 422,
    ApiErrorId.ERR_CHILD_INELIGIBLE: 422,
    ApiErrorId.ERR_SSI_RESOURCES_EXCEEDED: 422,
    ApiErrorId.ERR_CDR_NOT_DUE: 422,
    ApiErrorId.ERR_INVALID_PAGINATION: 422,
    ApiErrorId.ERR_BAD_REQUEST: 400,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map({k.value: v for k, v in HTTP_STATUS_CODES.items()})


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
