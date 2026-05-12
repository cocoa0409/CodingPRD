"""Error IDs and HTTP status mapping (PRD §5).

Registered with the framework so validate_error() auto-checks status codes
without each test having to pass an expected_status argument.
"""
from __future__ import annotations
from enum import Enum

from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    # --- Auth / RBAC / existence ---
    ERR_AUTH_MISSING = "ERR_AUTH_MISSING"
    ERR_AUTH_INVALID_ROLE = "ERR_AUTH_INVALID_ROLE"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"

    # --- State / OCC ---
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_STALE_VERSION = "ERR_STALE_VERSION"

    # --- Business safety ---
    ERR_PET_ARCHIVED = "ERR_PET_ARCHIVED"
    ERR_OWNER_NOT_VERIFIED = "ERR_OWNER_NOT_VERIFIED"
    ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
    ERR_DOSAGE_OUT_OF_RANGE = "ERR_DOSAGE_OUT_OF_RANGE"
    ERR_SEVERE_INTERACTION = "ERR_SEVERE_INTERACTION"

    # --- Business referential ---
    ERR_PENDING_PRESCRIPTIONS = "ERR_PENDING_PRESCRIPTIONS"
    ERR_LAB_ITEMS_INVALID = "ERR_LAB_ITEMS_INVALID"

    # --- Business constraint / temporal ---
    ERR_CAGE_CAPACITY_EXCEEDED = "ERR_CAGE_CAPACITY_EXCEEDED"
    ERR_CAGE_OVERLAP_CAPACITY = "ERR_CAGE_OVERLAP_CAPACITY"
    ERR_VACCINE_AGE_MIN = "ERR_VACCINE_AGE_MIN"
    ERR_VACCINE_COOLDOWN = "ERR_VACCINE_COOLDOWN"
    ERR_BATCH_RECALLED = "ERR_BATCH_RECALLED"

    # --- Business fiscal ---
    ERR_INSUFFICIENT_DEPOSIT = "ERR_INSUFFICIENT_DEPOSIT"
    ERR_REFUND_EXCEEDS_PAID = "ERR_REFUND_EXCEEDS_PAID"

    # --- Idempotency / concurrency ---
    ERR_DUPLICATE_EVENT = "ERR_DUPLICATE_EVENT"
    ERR_PRESCRIPTION_ALREADY_REVIEWED = "ERR_PRESCRIPTION_ALREADY_REVIEWED"

    # --- Routing / generic ---
    ERR_NO_VET_AVAILABLE = "ERR_NO_VET_AVAILABLE"
    ERR_VALIDATION_FAILED = "ERR_VALIDATION_FAILED"


HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_AUTH_MISSING: 401,
    ApiErrorId.ERR_AUTH_INVALID_ROLE: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_REFERENCE_NOT_FOUND: 422,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_STALE_VERSION: 409,
    ApiErrorId.ERR_PET_ARCHIVED: 409,
    ApiErrorId.ERR_OWNER_NOT_VERIFIED: 409,
    ApiErrorId.ERR_SEGREGATION_OF_DUTIES: 403,
    ApiErrorId.ERR_DOSAGE_OUT_OF_RANGE: 422,
    ApiErrorId.ERR_SEVERE_INTERACTION: 422,
    ApiErrorId.ERR_PENDING_PRESCRIPTIONS: 409,
    ApiErrorId.ERR_LAB_ITEMS_INVALID: 422,
    ApiErrorId.ERR_CAGE_CAPACITY_EXCEEDED: 409,
    ApiErrorId.ERR_CAGE_OVERLAP_CAPACITY: 409,
    ApiErrorId.ERR_VACCINE_AGE_MIN: 422,
    ApiErrorId.ERR_VACCINE_COOLDOWN: 422,
    ApiErrorId.ERR_BATCH_RECALLED: 422,
    ApiErrorId.ERR_INSUFFICIENT_DEPOSIT: 402,
    ApiErrorId.ERR_REFUND_EXCEEDS_PAID: 422,
    ApiErrorId.ERR_DUPLICATE_EVENT: 409,
    ApiErrorId.ERR_PRESCRIPTION_ALREADY_REVIEWED: 409,
    ApiErrorId.ERR_NO_VET_AVAILABLE: 409,
    ApiErrorId.ERR_VALIDATION_FAILED: 422,
}


# Register with framework — validate_error() will cross-check HTTP status.
set_error_http_status_map({k.value: v for k, v in HTTP_STATUS_CODES.items()})


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
