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
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    # PRD §2.7 — existence
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"
    # PRD §2.8 — state & cross-entity
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_CROSS_ENTITY_PRECONDITION = "ERR_CROSS_ENTITY_PRECONDITION"
    # PRD §2.8 / §3.3 — segregation of duties
    ERR_SEGREGATION_VIOLATION = "ERR_SEGREGATION_VIOLATION"
    # PRD §3.7 — discharge
    ERR_INELIGIBLE_DISCHARGE = "ERR_INELIGIBLE_DISCHARGE"
    # PRD §3.3 — supplemental claim referential
    ERR_SUPPLEMENTAL_REFERENCE_INVALID = "ERR_SUPPLEMENTAL_REFERENCE_INVALID"
    # PRD §3.6 — enrollment temporal
    ERR_INVALID_TERM_RANGE = "ERR_INVALID_TERM_RANGE"
    ERR_ENROLLMENT_OVERLAP = "ERR_ENROLLMENT_OVERLAP"
    # PRD §3.10 — housing payment temporal & uniqueness
    ERR_PAYMENT_OUTSIDE_TERM = "ERR_PAYMENT_OUTSIDE_TERM"
    ERR_PAYMENT_ALREADY_POSTED = "ERR_PAYMENT_ALREADY_POSTED"
    # PRD §3.2 — dependents
    ERR_DEPENDENT_AGE = "ERR_DEPENDENT_AGE"
    ERR_DUPLICATE_SPOUSE = "ERR_DUPLICATE_SPOUSE"
    # PRD §3.9 — entitlement fiscal
    ERR_ENTITLEMENT_EXCEEDED = "ERR_ENTITLEMENT_EXCEEDED"
    # PRD §3.7 — Yellow Ribbon
    ERR_YELLOW_RIBBON_CAP_EXCEEDED = "ERR_YELLOW_RIBBON_CAP_EXCEEDED"
    # PRD §3.3 — granted rating
    ERR_INVALID_RATING = "ERR_INVALID_RATING"
    # PRD §2.5 — OCC
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"
    # PRD §2.11 — supplemental concurrency
    ERR_DUPLICATE_SUPPLEMENTAL = "ERR_DUPLICATE_SUPPLEMENTAL"


# PRD §5 — Error Code Catalogue (HTTP status mapping).
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_REFERENCE_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_CROSS_ENTITY_PRECONDITION: 409,
    ApiErrorId.ERR_SEGREGATION_VIOLATION: 403,
    ApiErrorId.ERR_INELIGIBLE_DISCHARGE: 403,
    ApiErrorId.ERR_SUPPLEMENTAL_REFERENCE_INVALID: 422,
    ApiErrorId.ERR_INVALID_TERM_RANGE: 422,
    ApiErrorId.ERR_ENROLLMENT_OVERLAP: 409,
    ApiErrorId.ERR_PAYMENT_OUTSIDE_TERM: 422,
    ApiErrorId.ERR_PAYMENT_ALREADY_POSTED: 409,
    ApiErrorId.ERR_DEPENDENT_AGE: 422,
    ApiErrorId.ERR_DUPLICATE_SPOUSE: 409,
    ApiErrorId.ERR_ENTITLEMENT_EXCEEDED: 422,
    ApiErrorId.ERR_YELLOW_RIBBON_CAP_EXCEEDED: 422,
    ApiErrorId.ERR_INVALID_RATING: 422,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_DUPLICATE_SUPPLEMENTAL: 409,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map({k.value: v for k, v in HTTP_STATUS_CODES.items()})


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
