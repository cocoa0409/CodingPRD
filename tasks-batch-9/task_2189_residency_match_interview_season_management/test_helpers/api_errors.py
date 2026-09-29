"""Error identifiers and their HTTP status mapping (PRD §5).

The mapping is registered with the shared validator layer at import time so
that ``validate_error(response, ApiErrorId.ERR_X)`` also asserts the HTTP
status code declared by the PRD for that identifier.
"""

from enum import Enum

from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    """Every error identifier the API is allowed to return (PRD §5)."""

    # --- identity, authorisation and lookup -------------------------------
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
    ERR_OWNERSHIP_MISMATCH = "ERR_OWNERSHIP_MISMATCH"
    ERR_RESOURCE_NOT_FOUND = "ERR_RESOURCE_NOT_FOUND"

    # --- shape and state --------------------------------------------------
    ERR_VALIDATION = "ERR_VALIDATION"
    ERR_INVALID_STATE = "ERR_INVALID_STATE"

    # --- optimistic concurrency ------------------------------------------
    ERR_STALE_RANK_LIST_VERSION = "ERR_STALE_RANK_LIST_VERSION"
    ERR_STALE_WAVE_VERSION = "ERR_STALE_WAVE_VERSION"

    # --- integrity of the match process ----------------------------------
    ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
    ERR_CONFLICT_OF_INTEREST = "ERR_CONFLICT_OF_INTEREST"
    ERR_UNRESOLVED_COMMUNICATION_FLAG = "ERR_UNRESOLVED_COMMUNICATION_FLAG"
    ERR_CROSS_REFERENCE_MISMATCH = "ERR_CROSS_REFERENCE_MISMATCH"

    # --- deadlines and expiry instants -----------------------------------
    ERR_INVITATION_EXPIRED = "ERR_INVITATION_EXPIRED"
    ERR_SOAP_OFFER_EXPIRED = "ERR_SOAP_OFFER_EXPIRED"
    ERR_CERTIFICATION_DEADLINE_PASSED = "ERR_CERTIFICATION_DEADLINE_PASSED"

    # --- temporal and uniqueness conflicts -------------------------------
    ERR_INTERVIEWER_DOUBLE_BOOKED = "ERR_INTERVIEWER_DOUBLE_BOOKED"
    ERR_WAVE_WINDOW_CONFLICT = "ERR_WAVE_WINDOW_CONFLICT"
    ERR_SLOT_TIMING_VIOLATION = "ERR_SLOT_TIMING_VIOLATION"
    ERR_DUPLICATE_RESOURCE = "ERR_DUPLICATE_RESOURCE"

    # --- domain business rules -------------------------------------------
    ERR_SCREENING_FILTER_FAILED = "ERR_SCREENING_FILTER_FAILED"
    ERR_INSUFFICIENT_EVALUATIONS = "ERR_INSUFFICIENT_EVALUATIONS"
    ERR_RANK_POSITION_SEQUENCE = "ERR_RANK_POSITION_SEQUENCE"
    ERR_CREDENTIALS_INCOMPLETE = "ERR_CREDENTIALS_INCOMPLETE"

    # --- capacity and budget ceilings ------------------------------------
    ERR_SLOT_FULL = "ERR_SLOT_FULL"
    ERR_WAVE_CAPACITY_REACHED = "ERR_WAVE_CAPACITY_REACHED"
    ERR_SOAP_BUDGET_EXCEEDED = "ERR_SOAP_BUDGET_EXCEEDED"
    ERR_RANK_LIST_TOO_LONG = "ERR_RANK_LIST_TOO_LONG"
    ERR_NO_POSITIONS_AVAILABLE = "ERR_NO_POSITIONS_AVAILABLE"


HTTP_STATUS_CODES: dict[str, int] = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN_ROLE: 403,
    ApiErrorId.ERR_OWNERSHIP_MISMATCH: 403,
    ApiErrorId.ERR_RESOURCE_NOT_FOUND: 404,
    ApiErrorId.ERR_VALIDATION: 422,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_STALE_RANK_LIST_VERSION: 412,
    ApiErrorId.ERR_STALE_WAVE_VERSION: 412,
    ApiErrorId.ERR_SEGREGATION_OF_DUTIES: 422,
    ApiErrorId.ERR_CONFLICT_OF_INTEREST: 422,
    ApiErrorId.ERR_UNRESOLVED_COMMUNICATION_FLAG: 422,
    ApiErrorId.ERR_CROSS_REFERENCE_MISMATCH: 422,
    ApiErrorId.ERR_INVITATION_EXPIRED: 409,
    ApiErrorId.ERR_SOAP_OFFER_EXPIRED: 409,
    ApiErrorId.ERR_CERTIFICATION_DEADLINE_PASSED: 409,
    ApiErrorId.ERR_INTERVIEWER_DOUBLE_BOOKED: 409,
    ApiErrorId.ERR_WAVE_WINDOW_CONFLICT: 409,
    ApiErrorId.ERR_SLOT_TIMING_VIOLATION: 409,
    ApiErrorId.ERR_DUPLICATE_RESOURCE: 409,
    ApiErrorId.ERR_SCREENING_FILTER_FAILED: 422,
    ApiErrorId.ERR_INSUFFICIENT_EVALUATIONS: 422,
    ApiErrorId.ERR_RANK_POSITION_SEQUENCE: 422,
    ApiErrorId.ERR_CREDENTIALS_INCOMPLETE: 409,
    ApiErrorId.ERR_SLOT_FULL: 409,
    ApiErrorId.ERR_WAVE_CAPACITY_REACHED: 409,
    ApiErrorId.ERR_SOAP_BUDGET_EXCEEDED: 409,
    ApiErrorId.ERR_RANK_LIST_TOO_LONG: 409,
    ApiErrorId.ERR_NO_POSITIONS_AVAILABLE: 409,
}

set_error_http_status_map(HTTP_STATUS_CODES)
