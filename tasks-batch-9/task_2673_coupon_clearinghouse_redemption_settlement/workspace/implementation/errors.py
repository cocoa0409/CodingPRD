"""Error catalogue for the coupon clearinghouse API (PRD section 5)."""

ERROR_STATUS = {
    # Authentication / authorisation
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SOD_VIOLATION": 403,
    # Request shape
    "ERR_INVALID_REQUEST": 400,
    # Existence
    "ERR_MANUFACTURER_NOT_FOUND": 404,
    "ERR_RETAILER_NOT_FOUND": 404,
    "ERR_OFFER_NOT_FOUND": 404,
    "ERR_SUBMISSION_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_COUPON_ITEM_NOT_FOUND": 404,
    "ERR_PURCHASE_RECORD_NOT_FOUND": 404,
    "ERR_STATEMENT_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_DISPUTE_NOT_FOUND": 404,
    "ERR_CLIP_NOT_FOUND": 404,
    "ERR_REDEMPTION_EVENT_NOT_FOUND": 404,
    "ERR_NOT_FOUND": 404,
    # Optimistic concurrency
    "ERR_STALE_SUBMISSION_VERSION": 412,
    "ERR_STALE_RETAILER_VERSION": 412,
    # State
    "ERR_INVALID_STATE_TRANSITION": 409,
    # Standing
    "ERR_RETAILER_SUSPENDED": 403,
    "ERR_MANUFACTURER_SUSPENDED": 403,
    # Cross-entity coherence
    "ERR_OFFER_MANUFACTURER_MISMATCH": 422,
    "ERR_OFFER_NOT_CLEARABLE": 422,
    "ERR_DISPUTE_OPEN": 409,
    "ERR_INVOICE_NOT_FUNDED": 422,
    "ERR_STATEMENT_ALREADY_PAID": 409,
    "ERR_STATEMENT_NOT_BILLABLE": 422,
    "ERR_OFFER_NOT_DIGITAL": 422,
    "ERR_OFFER_EXPIRED": 422,
    # Clock
    "ERR_CLOCK_NOT_MONOTONIC": 422,
    # Windows / overlaps / limits
    "ERR_POSTMARK_WINDOW_OVERLAP": 409,
    "ERR_BILLING_PERIOD_BUFFER_VIOLATION": 409,
    "ERR_CLIP_CONCURRENCY_LIMIT": 409,
    "ERR_SUBMISSION_PAST_GRACE": 422,
    "ERR_DISPUTE_WINDOW_CLOSED": 422,
    "ERR_DUPLICATE_OFFER_CODE": 409,
    "ERR_DUPLICATE_GS1_PREFIX": 409,
    "ERR_CHANNEL_NOT_SUPPORTED": 422,
    "ERR_EMPTY_SUBMISSION": 422,
    "ERR_COUNT_VARIANCE_EXCEEDED": 422,
    "ERR_LOT_COUNT_OVERFLOW": 422,
    "ERR_IMAGE_REQUIRED": 422,
    "ERR_POS_REF_REQUIRED": 422,
    "ERR_LOT_CAPTURE_COMPLETE": 409,
    "ERR_SAMPLE_INCOMPLETE": 422,
    "ERR_INFO_ROUND_LIMIT": 422,
    "ERR_STATEMENT_LINES_EMPTY": 422,
    "ERR_MAX_REDEMPTIONS_EXCEEDED": 422,
    "ERR_FUNDING_EXCEEDS_BILLED": 422,
    "ERR_PAY_DATE_NOT_REACHED": 422,
}


class ApiError(Exception):
    """Raised anywhere in the request path; converted into the error envelope."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    body = error_id[4:] if error_id.startswith("ERR_") else error_id
    return body.replace("_", " ").capitalize()


def bad_request(message):
    return ApiError("ERR_INVALID_REQUEST", message)
