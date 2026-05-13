"""Error IDs and HTTP status mapping for the Travel Reimburse API.

Each error_id and its HTTP status is taken verbatim from PRD §5
(Error Code Catalogue). The mapping is registered with the framework so
validate_error() can auto-check HTTP status from the registered map.
"""
from __future__ import annotations
from enum import Enum
from typing import Dict

from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    ERR_AUTH_MISSING = "ERR_AUTH_MISSING"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    ERR_NOT_CURRENT_APPROVER = "ERR_NOT_CURRENT_APPROVER"
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_REFERENCE_INVALID = "ERR_REFERENCE_INVALID"
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"
    ERR_VALIDATION = "ERR_VALIDATION"
    ERR_NO_ACTIVE_STANDARD = "ERR_NO_ACTIVE_STANDARD"
    ERR_OPTION_NOT_ELIGIBLE = "ERR_OPTION_NOT_ELIGIBLE"
    ERR_SEGMENT_OUTSIDE_TRIP = "ERR_SEGMENT_OUTSIDE_TRIP"
    ERR_SEGMENT_TIME_OVERLAP = "ERR_SEGMENT_TIME_OVERLAP"
    ERR_HOTEL_NIGHT_OVERLAP = "ERR_HOTEL_NIGHT_OVERLAP"
    ERR_BUDGET_OVERRUN = "ERR_BUDGET_OVERRUN"
    ERR_INVOICE_DUPLICATE = "ERR_INVOICE_DUPLICATE"
    ERR_INVOICE_NOT_VERIFIED = "ERR_INVOICE_NOT_VERIFIED"
    ERR_INVOICE_NOT_MATCHED = "ERR_INVOICE_NOT_MATCHED"
    ERR_INVOICE_ALREADY_ATTACHED = "ERR_INVOICE_ALREADY_ATTACHED"
    ERR_IDEMPOTENT_REPLAY = "ERR_IDEMPOTENT_REPLAY"
    ERR_GM_APPROVAL_REQUIRED = "ERR_GM_APPROVAL_REQUIRED"
    ERR_PAYMENT_AMOUNT_MISMATCH = "ERR_PAYMENT_AMOUNT_MISMATCH"
    ERR_PAYMENT_RETRY_EXHAUSTED = "ERR_PAYMENT_RETRY_EXHAUSTED"
    ERR_INVALID_BATCH = "ERR_INVALID_BATCH"


HTTP_STATUS_CODES: Dict[str, int] = {
    ApiErrorId.ERR_AUTH_MISSING.value: 401,
    ApiErrorId.ERR_FORBIDDEN.value: 403,
    ApiErrorId.ERR_NOT_CURRENT_APPROVER.value: 403,
    ApiErrorId.ERR_NOT_FOUND.value: 404,
    ApiErrorId.ERR_REFERENCE_INVALID.value: 422,
    ApiErrorId.ERR_INVALID_STATE.value: 409,
    ApiErrorId.ERR_VERSION_CONFLICT.value: 409,
    ApiErrorId.ERR_VALIDATION.value: 422,
    ApiErrorId.ERR_NO_ACTIVE_STANDARD.value: 422,
    ApiErrorId.ERR_OPTION_NOT_ELIGIBLE.value: 422,
    ApiErrorId.ERR_SEGMENT_OUTSIDE_TRIP.value: 422,
    ApiErrorId.ERR_SEGMENT_TIME_OVERLAP.value: 422,
    ApiErrorId.ERR_HOTEL_NIGHT_OVERLAP.value: 422,
    ApiErrorId.ERR_BUDGET_OVERRUN.value: 422,
    ApiErrorId.ERR_INVOICE_DUPLICATE.value: 409,
    ApiErrorId.ERR_INVOICE_NOT_VERIFIED.value: 422,
    ApiErrorId.ERR_INVOICE_NOT_MATCHED.value: 422,
    ApiErrorId.ERR_INVOICE_ALREADY_ATTACHED.value: 409,
    ApiErrorId.ERR_IDEMPOTENT_REPLAY.value: 409,
    ApiErrorId.ERR_GM_APPROVAL_REQUIRED.value: 422,
    ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value: 422,
    ApiErrorId.ERR_PAYMENT_RETRY_EXHAUSTED.value: 422,
    ApiErrorId.ERR_INVALID_BATCH.value: 422,
}

# Register the mapping with the framework. validate_error() will
# auto-check HTTP status without callers needing to pass expected_status.
set_error_http_status_map(HTTP_STATUS_CODES)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
