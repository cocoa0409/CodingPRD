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
    # auth / authz
    ERR_AUTH_MISSING = "ERR_AUTH_MISSING"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    ERR_SEGREGATION_VIOLATION = "ERR_SEGREGATION_VIOLATION"

    # existence
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"

    # state / OCC
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"

    # cross-entity & business-safety
    ERR_TASK_NOT_RESOLVABLE = "ERR_TASK_NOT_RESOLVABLE"
    ERR_DECISION_NOT_FINALIZED = "ERR_DECISION_NOT_FINALIZED"

    # business referential / temporal / constraint
    ERR_EVIDENCE_REQUIRED = "ERR_EVIDENCE_REQUIRED"
    ERR_INVOICE_VALUE_REQUIRED = "ERR_INVOICE_VALUE_REQUIRED"
    ERR_VEHICLE_OVERLAP = "ERR_VEHICLE_OVERLAP"
    ERR_DRIVER_HOURS_EXCEEDED = "ERR_DRIVER_HOURS_EXCEEDED"
    ERR_READING_OUT_OF_WINDOW = "ERR_READING_OUT_OF_WINDOW"
    ERR_PCT_SUM_INVALID = "ERR_PCT_SUM_INVALID"
    ERR_INSURANCE_CAP_EXCEEDED = "ERR_INSURANCE_CAP_EXCEEDED"
    ERR_QUANTITY_INVALID = "ERR_QUANTITY_INVALID"
    ERR_AMOUNT_INVALID = "ERR_AMOUNT_INVALID"

    # idempotency / uniqueness / generic schema
    ERR_IDEMPOTENT_REPLAY = "ERR_IDEMPOTENT_REPLAY"
    ERR_HANDOVER_ALREADY_EXISTS = "ERR_HANDOVER_ALREADY_EXISTS"
    ERR_VALIDATION = "ERR_VALIDATION"


HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_AUTH_MISSING: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_SEGREGATION_VIOLATION: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_REFERENCE_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_TASK_NOT_RESOLVABLE: 409,
    ApiErrorId.ERR_DECISION_NOT_FINALIZED: 409,
    ApiErrorId.ERR_VEHICLE_OVERLAP: 409,
    ApiErrorId.ERR_DRIVER_HOURS_EXCEEDED: 409,
    ApiErrorId.ERR_HANDOVER_ALREADY_EXISTS: 409,
    ApiErrorId.ERR_EVIDENCE_REQUIRED: 422,
    ApiErrorId.ERR_INVOICE_VALUE_REQUIRED: 422,
    ApiErrorId.ERR_READING_OUT_OF_WINDOW: 422,
    ApiErrorId.ERR_PCT_SUM_INVALID: 422,
    ApiErrorId.ERR_INSURANCE_CAP_EXCEEDED: 422,
    ApiErrorId.ERR_QUANTITY_INVALID: 422,
    ApiErrorId.ERR_AMOUNT_INVALID: 422,
    ApiErrorId.ERR_VALIDATION: 422,
    ApiErrorId.ERR_IDEMPOTENT_REPLAY: 200,
}


# Register so validate_error() can auto-check status codes
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()}
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
