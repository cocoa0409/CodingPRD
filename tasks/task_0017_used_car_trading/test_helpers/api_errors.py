"""Error IDs and HTTP status mapping (PRD §5).

Registers the mapping with the framework so ``validate_error()`` can
auto-check HTTP status codes.

Note on ``ERR_IDEMPOTENCY_REPLAY`` — PRD §2.10 explicitly says the replay
marker is informational, not a rejection, returned with HTTP 200. It is
therefore mapped to 200 here so ``validate_error`` accepts the success-shaped
status code; tests that need to assert the marker must use the bespoke flow
(checking the body's ``error_id`` directly while the response is 200).
"""

from enum import Enum

from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    ERR_AUTH_MISSING = "ERR_AUTH_MISSING"
    ERR_AUTH_INVALID = "ERR_AUTH_INVALID"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_NOT_OWNER = "ERR_NOT_OWNER"
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_VIN_INVALID = "ERR_VIN_INVALID"
    ERR_ASSESSMENT_NOT_FINALIZED = "ERR_ASSESSMENT_NOT_FINALIZED"
    ERR_ASSESSMENT_VERSION_STALE = "ERR_ASSESSMENT_VERSION_STALE"
    ERR_LISTING_DOCS_INSUFFICIENT = "ERR_LISTING_DOCS_INSUFFICIENT"
    ERR_BID_TOO_LOW = "ERR_BID_TOO_LOW"
    ERR_LISTING_NOT_RESERVABLE = "ERR_LISTING_NOT_RESERVABLE"
    ERR_RESERVATION_QUEUED_NOT_HOLDING = "ERR_RESERVATION_QUEUED_NOT_HOLDING"
    ERR_DEPOSIT_LIMIT_EXCEEDED = "ERR_DEPOSIT_LIMIT_EXCEEDED"
    ERR_DOWN_PAYMENT_INSUFFICIENT = "ERR_DOWN_PAYMENT_INSUFFICIENT"
    ERR_LOAN_PARAMS_INVALID = "ERR_LOAN_PARAMS_INVALID"
    ERR_APPOINTMENT_OUT_OF_WINDOW = "ERR_APPOINTMENT_OUT_OF_WINDOW"
    ERR_TRANSFER_DOCS_INCOMPLETE = "ERR_TRANSFER_DOCS_INCOMPLETE"
    ERR_WARRANTY_NOT_ACTIVE = "ERR_WARRANTY_NOT_ACTIVE"
    ERR_COMPONENT_NOT_COVERED = "ERR_COMPONENT_NOT_COVERED"
    ERR_DISPUTE_ROUNDS_EXHAUSTED = "ERR_DISPUTE_ROUNDS_EXHAUSTED"
    ERR_DISPUTE_NOT_ELIGIBLE = "ERR_DISPUTE_NOT_ELIGIBLE"
    ERR_IDEMPOTENCY_REPLAY = "ERR_IDEMPOTENCY_REPLAY"
    ERR_PAGINATION_INVALID = "ERR_PAGINATION_INVALID"
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"
    # Generic invalid-request fallback for malformed payloads. PRD §3 prose
    # treats these as 400/422 family — tests use validate_error_is_one_of
    # rather than asserting an exact id when the PRD does not commit to one.
    ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"


HTTP_STATUS_CODES = {
    ApiErrorId.ERR_AUTH_MISSING: 401,
    ApiErrorId.ERR_AUTH_INVALID: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_NOT_OWNER: 403,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_VIN_INVALID: 422,
    ApiErrorId.ERR_ASSESSMENT_NOT_FINALIZED: 422,
    ApiErrorId.ERR_ASSESSMENT_VERSION_STALE: 409,
    ApiErrorId.ERR_LISTING_DOCS_INSUFFICIENT: 422,
    ApiErrorId.ERR_BID_TOO_LOW: 422,
    ApiErrorId.ERR_LISTING_NOT_RESERVABLE: 409,
    ApiErrorId.ERR_RESERVATION_QUEUED_NOT_HOLDING: 409,
    ApiErrorId.ERR_DEPOSIT_LIMIT_EXCEEDED: 422,
    ApiErrorId.ERR_DOWN_PAYMENT_INSUFFICIENT: 422,
    ApiErrorId.ERR_LOAN_PARAMS_INVALID: 422,
    ApiErrorId.ERR_APPOINTMENT_OUT_OF_WINDOW: 422,
    ApiErrorId.ERR_TRANSFER_DOCS_INCOMPLETE: 422,
    ApiErrorId.ERR_WARRANTY_NOT_ACTIVE: 409,
    ApiErrorId.ERR_COMPONENT_NOT_COVERED: 422,
    ApiErrorId.ERR_DISPUTE_ROUNDS_EXHAUSTED: 409,
    ApiErrorId.ERR_DISPUTE_NOT_ELIGIBLE: 422,
    ApiErrorId.ERR_IDEMPOTENCY_REPLAY: 200,
    ApiErrorId.ERR_PAGINATION_INVALID: 400,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_INVALID_REQUEST: 400,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map({k.value: v for k, v in HTTP_STATUS_CODES.items()})
