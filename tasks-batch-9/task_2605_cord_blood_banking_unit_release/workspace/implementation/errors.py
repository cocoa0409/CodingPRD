"""Complete error catalogue (PRD 5) and the ApiError exception."""

ERROR_HTTP = {
    # authentication and authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # request shape
    "ERR_VALIDATION_FAILED": 422,
    # existence
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_STORAGE_ACCOUNT_NOT_FOUND": 404,
    "ERR_KIT_NOT_FOUND": 404,
    "ERR_COLLECTION_NOT_FOUND": 404,
    "ERR_UNIT_NOT_FOUND": 404,
    "ERR_PROCESSING_RUN_NOT_FOUND": 404,
    "ERR_QUALITY_TEST_NOT_FOUND": 404,
    "ERR_SCREENING_NOT_FOUND": 404,
    "ERR_TANK_NOT_FOUND": 404,
    "ERR_EXCURSION_NOT_FOUND": 404,
    "ERR_LISTING_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_RESERVATION_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_UNIT_VERSION": 412,
    # state preconditions
    "ERR_INVALID_ENROLLMENT_STATE": 409,
    "ERR_INVALID_KIT_STATE": 409,
    "ERR_INVALID_COLLECTION_STATE": 409,
    "ERR_INVALID_UNIT_STATE": 409,
    "ERR_INVALID_RUN_STATE": 409,
    "ERR_INVALID_EXCURSION_STATE": 409,
    "ERR_INVALID_RESERVATION_STATE": 409,
    "ERR_INVALID_INVOICE_STATE": 409,
    "ERR_INVALID_LISTING_STATE": 409,
    # consent
    "ERR_CONSENT_NOT_CURRENT": 409,
    "ERR_CONSENT_AMENDMENT_LIMIT": 409,
    # maternal screening and clinical safety
    "ERR_MATERNAL_SCREENING_INCOMPLETE": 409,
    "ERR_MATERNAL_SCREENING_REACTIVE": 422,
    "ERR_STERILITY_POSITIVE": 422,
    "ERR_NO_QUALITY_TEST": 409,
    "ERR_CONFIRMATORY_TEST_REQUIRED": 409,
    "ERR_UNIT_NOT_ELIGIBLE": 409,
    "ERR_DOSE_BELOW_MINIMUM": 422,
    "ERR_QUALITY_BELOW_PUBLIC_THRESHOLD": 422,
    # constraints and uniqueness
    "ERR_PROGRAM_TYPE_MISMATCH": 422,
    "ERR_DUPLICATE_STORAGE_ACCOUNT": 409,
    "ERR_DUPLICATE_ACTIVE_LISTING": 409,
    "ERR_KIT_EXPIRED": 409,
    # temporal
    "ERR_PROCESSING_WINDOW_EXCEEDED": 422,
    "ERR_TRANSPORT_TEMP_OUT_OF_RANGE": 422,
    "ERR_MAINTENANCE_WINDOW_CONFLICT": 409,
    "ERR_HOLD_WINDOW_CONFLICT": 409,
    "ERR_CONFIRMATION_WINDOW_EXPIRED": 409,
    # capacity and facility
    "ERR_TANK_CAPACITY_EXCEEDED": 409,
    "ERR_TANK_NOT_OPERATIONAL": 409,
    "ERR_EXCURSION_LIMIT_EXCEEDED": 409,
    # fiscal
    "ERR_ACCOUNT_DELINQUENT": 402,
    "ERR_OUTSTANDING_BALANCE": 402,
    "ERR_PAYMENT_EXCEEDS_BALANCE": 422,
    # generic routing fallback
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    body = error_id[4:] if error_id.startswith("ERR_") else error_id
    return body.replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)
