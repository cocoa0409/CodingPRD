"""Error IDs and HTTP status mapping — PRD §5 Error Code Catalogue.

After definition, the mapping is registered with the framework so
validate_error() auto-checks HTTP status codes without each test
passing them explicitly.
"""
from __future__ import annotations

from enum import Enum

from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    # PRD §2.1 — auth
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    ERR_NOT_OWNER = "ERR_NOT_OWNER"
    # PRD §2.7, §2.10 — existence
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    # PRD §2.10, §3 — state
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    # PRD §2.11, §3.6 — segregation of duties
    ERR_SEGREGATION_OF_DUTIES_VIOLATION = "ERR_SEGREGATION_OF_DUTIES_VIOLATION"
    # PRD §3.6 — appeals
    ERR_APPEAL_WINDOW_EXPIRED = "ERR_APPEAL_WINDOW_EXPIRED"
    ERR_STALE_APPEAL_SUBJECT = "ERR_STALE_APPEAL_SUBJECT"
    ERR_APPEAL_ALREADY_FILED = "ERR_APPEAL_ALREADY_FILED"
    # PRD §3.3 — weekly certifications
    ERR_NOT_SATURDAY = "ERR_NOT_SATURDAY"
    ERR_WEEK_OUT_OF_RANGE = "ERR_WEEK_OUT_OF_RANGE"
    ERR_DUPLICATE_WEEK = "ERR_DUPLICATE_WEEK"
    ERR_INSUFFICIENT_WORK_SEARCH = "ERR_INSUFFICIENT_WORK_SEARCH"
    ERR_BENEFIT_YEAR_EXPIRED = "ERR_BENEFIT_YEAR_EXPIRED"
    # PRD §3.5 — overpayment
    ERR_REPAY_EXCEEDS_BALANCE = "ERR_REPAY_EXCEEDS_BALANCE"
    ERR_FRAUD_NOT_WAIVABLE = "ERR_FRAUD_NOT_WAIVABLE"
    ERR_STATUTE_NOT_REACHED = "ERR_STATUTE_NOT_REACHED"
    # PRD §3.2 — monetary eligibility
    ERR_INSUFFICIENT_BASE_PERIOD_WAGES = "ERR_INSUFFICIENT_BASE_PERIOD_WAGES"
    # PRD §3.4 — extension
    ERR_NO_ACTIVE_EXTENSION = "ERR_NO_ACTIVE_EXTENSION"
    ERR_EXTENSION_ALREADY_APPLIED = "ERR_EXTENSION_ALREADY_APPLIED"
    # PRD §2.5, §2.10 — optimistic concurrency
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"
    # PRD §2.10 — generic body validation
    ERR_VALIDATION_FAILED = "ERR_VALIDATION_FAILED"


# PRD §5 Error Code Catalogue: HTTP status mapping.
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_OWNER: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION: 403,
    ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED: 409,
    ApiErrorId.ERR_STALE_APPEAL_SUBJECT: 409,
    ApiErrorId.ERR_APPEAL_ALREADY_FILED: 409,
    ApiErrorId.ERR_NOT_SATURDAY: 422,
    ApiErrorId.ERR_WEEK_OUT_OF_RANGE: 409,
    ApiErrorId.ERR_DUPLICATE_WEEK: 409,
    ApiErrorId.ERR_INSUFFICIENT_WORK_SEARCH: 422,
    ApiErrorId.ERR_BENEFIT_YEAR_EXPIRED: 409,
    ApiErrorId.ERR_REPAY_EXCEEDS_BALANCE: 409,
    ApiErrorId.ERR_FRAUD_NOT_WAIVABLE: 403,
    ApiErrorId.ERR_INSUFFICIENT_BASE_PERIOD_WAGES: 422,
    ApiErrorId.ERR_NO_ACTIVE_EXTENSION: 409,
    ApiErrorId.ERR_EXTENSION_ALREADY_APPLIED: 409,
    ApiErrorId.ERR_STATUTE_NOT_REACHED: 409,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_VALIDATION_FAILED: 422,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map({k.value: v for k, v in HTTP_STATUS_CODES.items()})


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
