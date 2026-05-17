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
    # Auth / RBAC — PRD §2.1.
    ERR_AUTH_MISSING = "ERR_AUTH_MISSING"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"

    # Existence — PRD §2.5.
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"

    # State eligibility — PRD §2.6 / §3.*.
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_EPISODE_NOT_ACTIVE = "ERR_EPISODE_NOT_ACTIVE"
    ERR_REEVAL_DUE = "ERR_REEVAL_DUE"

    # Clinical-capability — PRD §3.2 / §3.9.
    ERR_THERAPIST_NOT_LICENSED_TO_EVALUATE = (
        "ERR_THERAPIST_NOT_LICENSED_TO_EVALUATE"
    )
    ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"

    # VA-referential — PRD §3.4.
    ERR_VETERAN_REFERRAL_REQUIRED = "ERR_VETERAN_REFERRAL_REQUIRED"
    ERR_VA_REFERENCE_MISMATCH = "ERR_VA_REFERENCE_MISMATCH"
    ERR_VA_REFERRAL_EXHAUSTED = "ERR_VA_REFERRAL_EXHAUSTED"

    # Temporal — PRD §3.3 / §3.5.
    ERR_CERT_PERIOD_TOO_LONG = "ERR_CERT_PERIOD_TOO_LONG"
    ERR_OUT_OF_AUTH_WINDOW = "ERR_OUT_OF_AUTH_WINDOW"
    ERR_CLINICIAN_DOUBLE_BOOKED = "ERR_CLINICIAN_DOUBLE_BOOKED"
    ERR_PATIENT_DOUBLE_BOOKED = "ERR_PATIENT_DOUBLE_BOOKED"

    # Quota / cap — PRD §2.7 / §2.8 / §3.5.
    ERR_POC_VISIT_LIMIT = "ERR_POC_VISIT_LIMIT"
    ERR_INSUFFICIENT_UNITS = "ERR_INSUFFICIENT_UNITS"
    ERR_CAP_EXCEEDED = "ERR_CAP_EXCEEDED"

    # Domain constraint — PRD §3.8.
    ERR_INVALID_MIPS_EXCEPTION = "ERR_INVALID_MIPS_EXCEPTION"

    # Pagination — PRD §2.3.
    ERR_PAGINATION_RANGE = "ERR_PAGINATION_RANGE"

    # OCC — PRD §2.4.
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"

    # Therapist registration — PRD §3.1.
    ERR_DUPLICATE_NPI = "ERR_DUPLICATE_NPI"

    # Generic shape — PRD §2.6.
    ERR_VALIDATION = "ERR_VALIDATION"


# PRD §5 Error Code Catalogue — explicit HTTP status mapping.
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_AUTH_MISSING: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_REFERENCE_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_EPISODE_NOT_ACTIVE: 409,
    ApiErrorId.ERR_REEVAL_DUE: 409,
    ApiErrorId.ERR_THERAPIST_NOT_LICENSED_TO_EVALUATE: 403,
    ApiErrorId.ERR_SEGREGATION_OF_DUTIES: 422,
    ApiErrorId.ERR_VETERAN_REFERRAL_REQUIRED: 422,
    ApiErrorId.ERR_VA_REFERENCE_MISMATCH: 422,
    ApiErrorId.ERR_VA_REFERRAL_EXHAUSTED: 409,
    ApiErrorId.ERR_CERT_PERIOD_TOO_LONG: 422,
    ApiErrorId.ERR_OUT_OF_AUTH_WINDOW: 422,
    ApiErrorId.ERR_CLINICIAN_DOUBLE_BOOKED: 409,
    ApiErrorId.ERR_PATIENT_DOUBLE_BOOKED: 409,
    ApiErrorId.ERR_POC_VISIT_LIMIT: 422,
    ApiErrorId.ERR_INSUFFICIENT_UNITS: 422,
    ApiErrorId.ERR_CAP_EXCEEDED: 422,
    ApiErrorId.ERR_INVALID_MIPS_EXCEPTION: 422,
    ApiErrorId.ERR_PAGINATION_RANGE: 400,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_DUPLICATE_NPI: 409,
    ApiErrorId.ERR_VALIDATION: 400,
}


# Register with the framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
