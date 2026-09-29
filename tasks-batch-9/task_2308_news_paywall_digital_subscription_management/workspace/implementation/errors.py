"""Error catalogue (PRD section 5 / SCAFFOLD errors)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_STATUS = {
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_OFFER_PLAN_NOT_FOUND": 404,
    "ERR_PAYWALL_RULE_NOT_FOUND": 404,
    "ERR_ARTICLE_NOT_FOUND": 404,
    "ERR_READER_NOT_FOUND": 404,
    "ERR_SUBSCRIPTION_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_CANCELLATION_REQUEST_NOT_FOUND": 404,
    "ERR_SAVE_OFFER_NOT_FOUND": 404,
    "ERR_HOLD_NOT_FOUND": 404,
    "ERR_GROUP_ACCOUNT_NOT_FOUND": 404,
    "ERR_SEAT_NOT_FOUND": 404,
    "ERR_STALE_OFFER_PLAN_VERSION": 412,
    "ERR_STALE_GROUP_ACCOUNT_VERSION": 412,
    "ERR_PLAN_NOT_ACTIVE": 409,
    "ERR_PLAN_ALREADY_ACTIVE": 409,
    "ERR_PRICE_CHANGE_STATE_INVALID": 409,
    "ERR_SUBSCRIPTION_TERMINAL": 409,
    "ERR_SUBSCRIPTION_NOT_ACTIVE": 409,
    "ERR_DUNNING_EXHAUSTED": 409,
    "ERR_INVOICE_NOT_PAYABLE": 409,
    "ERR_RETRY_TOO_EARLY": 409,
    "ERR_CANCELLATION_REQUEST_CLOSED": 409,
    "ERR_SAVE_OFFER_ALREADY_DECIDED": 409,
    "ERR_HOLD_NOT_RELEASABLE": 409,
    "ERR_SEAT_NOT_INVITED": 409,
    "ERR_SEAT_INVITE_EXPIRED": 409,
    "ERR_PRICE_NOTICE_WINDOW_TOO_SHORT": 422,
    "ERR_PRICE_NOTICE_NOT_SENT": 409,
    "ERR_PRICE_CHANGE_NOT_EFFECTIVE_YET": 409,
    "ERR_STEP_UP_SCHEDULE_INVALID": 422,
    "ERR_SAVE_OFFER_LIMIT_EXCEEDED": 409,
    "ERR_SAVE_OFFER_DISCOUNT_CAP": 422,
    "ERR_SEAT_DOMAIN_MISMATCH": 422,
    "ERR_GROUP_SUBSCRIPTION_NOT_ACTIVE": 422,
    "ERR_INTERVENTION_NOT_WARRANTED": 422,
    "ERR_EVENT_TYPE_SYSTEM_ONLY": 422,
    "ERR_READER_NOT_REGISTERED": 422,
    "ERR_ARTICLE_UNPUBLISHED": 422,
    "ERR_PLAN_NOT_PRINT_BUNDLE": 422,
    "ERR_PLAN_NOT_INSTITUTIONAL": 422,
    "ERR_HOLD_START_NOT_FUTURE": 422,
    "ERR_HOLD_START_IN_PAST": 422,
    "ERR_HOLD_INTERVAL_INVALID": 422,
    "ERR_HOLD_BUFFER_VIOLATION": 409,
    "ERR_VACATION_DAY_CAP_EXCEEDED": 422,
    "ERR_PAUSE_LIMIT_EXCEEDED": 409,
    "ERR_SEAT_INTERVAL_INVALID": 422,
    "ERR_SEAT_READER_DUPLICATE": 409,
    "ERR_SEAT_CAPACITY_EXCEEDED": 409,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
    "ERR_CLOCK_NOT_MONOTONIC": 422,
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
}

_DEFAULT_MESSAGES = {
    "ERR_MISSING_AUTH_HEADERS": "X-User-ID and X-User-Role headers are required and the role must be one of the five declared roles.",
    "ERR_UNAUTHORIZED": "The acting role is not permitted to perform this operation on this resource.",
    "ERR_SEGREGATION_OF_DUTIES": "The officer applying a price increase must differ from the officer who dispatched the notices.",
    "ERR_INVALID_REQUEST": "The request body or query is malformed.",
    "ERR_CLOCK_NOT_MONOTONIC": "The logical clock never moves backwards.",
}


def api_error(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)


def fail(error_id, message=None):
    raise api_error(error_id, message)
