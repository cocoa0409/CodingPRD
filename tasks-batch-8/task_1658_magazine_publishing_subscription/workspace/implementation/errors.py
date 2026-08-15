"""API error type and the full error catalog (error_id -> HTTP status)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERROR_STATUS = {
    # Auth
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    # Not found
    "ERR_PUBLICATION_NOT_FOUND": 404,
    "ERR_ISSUE_NOT_FOUND": 404,
    "ERR_SUBSCRIBER_NOT_FOUND": 404,
    "ERR_SUBSCRIPTION_NOT_FOUND": 404,
    "ERR_BATCH_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_AUDIT_NOT_FOUND": 404,
    "ERR_RENEWAL_EVENT_NOT_FOUND": 404,
    "ERR_SERIES_NOT_FOUND": 404,
    "ERR_DONOR_NOT_FOUND": 404,
    # State
    "ERR_INVALID_STATE": 409,
    "ERR_PUBLICATION_NOT_ACTIVE": 409,
    "ERR_ISSUE_NOT_AT_PRINTER": 409,
    "ERR_ISSUE_NOT_FINALIZED": 409,
    "ERR_ISSUE_PIPELINE_ACTIVE": 409,
    "ERR_ACTIVE_SUBSCRIPTIONS_REMAIN": 409,
    "ERR_LABELS_ALREADY_GENERATED": 409,
    "ERR_BATCH_ALREADY_GENERATED": 409,
    "ERR_BATCH_NOT_CONFIRMED": 409,
    "ERR_AD_CLOSE_LOCKED": 409,
    "ERR_AUDIT_NOT_QUALIFIED": 409,
    "ERR_AUDIT_NOT_FAILED": 409,
    # OCC
    "ERR_STALE_SUBSCRIPTION_VERSION": 412,
    "ERR_STALE_ISSUE_VERSION": 412,
    "ERR_STALE_BATCH_VERSION": 412,
    # Temporal
    "ERR_EDITORIAL_NOT_CLOSED_YET": 409,
    "ERR_AD_CLOSE_NOT_REACHED": 409,
    "ERR_PRINTER_DATE_NOT_REACHED": 409,
    "ERR_MAIL_DATE_NOT_REACHED": 409,
    "ERR_TENDER_TOO_EARLY": 409,
    "ERR_RENEWAL_WINDOW_NOT_OPEN": 409,
    # Referential
    "ERR_INVALID_START_ISSUE": 422,
    # Business: subscription/payment
    "ERR_PAID_REQUIRES_PAYMENT": 422,
    "ERR_CONTROLLED_MUST_BE_FREE": 422,
    "ERR_UNDELIVERABLE_ADDRESS": 422,
    # Business: postal
    "ERR_PAID_RATIO_BELOW_MINIMUM": 422,
    "ERR_AD_CONTENT_EXCEEDS_LIMIT": 422,
    "ERR_STANDARD_NO_CONTROLLED": 422,
    # Business: issue
    "ERR_NO_AD_PAGES": 422,
    "ERR_PRINT_RUN_TOO_SMALL": 422,
    # Business: inventory / fiscal
    "ERR_INSUFFICIENT_INVENTORY": 422,
    "ERR_UNRECOGNIZED_DEFERRED_REVENUE": 409,
    # Business: audit
    "ERR_INVALID_AUDIT_PERIOD": 422,
    "ERR_DRAFT_AUDIT_EXISTS": 422,
    "ERR_UNFILED_ISSUES_IN_PERIOD": 422,
    # Generic
    "ERR_INVALID_PAGINATION_PARAMETERS": 400,
    "ERR_INVALID_REQUEST": 400,
}


def err(error_id, message):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
