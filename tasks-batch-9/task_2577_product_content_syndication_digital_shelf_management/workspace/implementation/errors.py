"""Error catalog (PRD section 5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super(ApiError, self).__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGE.get(error_id, error_id)


ERROR_STATUS = {
    # authentication and authorisation
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_TRACK_ROLE_MISMATCH": 403,
    "ERR_RETAILER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_WAIVE_NOT_PERMITTED": 403,
    # request shape
    "ERR_INVALID_PAGINATION": 400,
    "ERR_INVALID_REQUEST": 400,
    "ERR_WINDOW_INVALID": 400,
    # not found
    "ERR_RETAILER_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_CONTENT_VERSION_NOT_FOUND": 404,
    "ERR_LISTING_NOT_FOUND": 404,
    "ERR_MEDIA_ASSET_NOT_FOUND": 404,
    "ERR_CHANGE_REQUEST_NOT_FOUND": 404,
    "ERR_SYNDICATION_JOB_NOT_FOUND": 404,
    "ERR_REJECTION_ERROR_NOT_FOUND": 404,
    "ERR_DEPLOYMENT_NOT_FOUND": 404,
    "ERR_ALERT_NOT_FOUND": 404,
    "ERR_NOT_FOUND": 404,
    # uniqueness
    "ERR_DUPLICATE_LISTING": 409,
    "ERR_DUPLICATE_REQUIREMENT": 409,
    # optimistic concurrency
    "ERR_STALE_VERSION": 412,
    # state guards
    "ERR_RETAILER_NOT_ACTIVE": 409,
    "ERR_VERSION_NOT_DRAFT": 409,
    "ERR_CHANGE_REQUEST_NOT_DRAFT": 409,
    "ERR_CHANGE_REQUEST_NOT_IN_REVIEW": 409,
    "ERR_TRACK_ALREADY_DECIDED": 409,
    "ERR_INVALID_JOB_STATE": 409,
    "ERR_REJECTION_ERROR_ALREADY_CLOSED": 409,
    "ERR_BLOCKING_ERRORS_UNRESOLVED": 409,
    "ERR_DEPLOYMENT_NOT_ACTIVE": 409,
    "ERR_ALERT_ALREADY_RESOLVED": 409,
    "ERR_LISTING_SHELF_BLOCKED": 409,
    "ERR_MEDIA_ASSET_NOT_PENDING": 409,
    # business rules
    "ERR_PROHIBITED_CLAIM": 422,
    "ERR_VERSION_NOT_PINNED": 422,
    "ERR_CHANGE_REQUEST_NOT_APPROVED": 422,
    "ERR_DEPLOYMENT_SCOPE_MISMATCH": 422,
    "ERR_MEDIA_ASSET_NOT_APPROVED": 422,
    "ERR_ATTRIBUTE_LENGTH_EXCEEDED": 422,
    "ERR_IMAGE_COUNT_BELOW_MINIMUM": 422,
    "ERR_COMPLETENESS_BELOW_THRESHOLD": 422,
    "ERR_ATTRIBUTE_KEY_UNKNOWN": 422,
    "ERR_DEPLOYMENT_WINDOW_OVERLAP": 409,
    "ERR_FEED_WINDOW_CONFLICT": 409,
    "ERR_FEED_CAPACITY_EXCEEDED": 409,
    "ERR_INTERNAL": 500,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and the role must be one of the seven declared roles.",
    "ERR_UNAUTHORIZED": "The acting role is not authorised for this endpoint.",
    "ERR_TRACK_ROLE_MISMATCH": "The acting role does not own the requested review track.",
    "ERR_RETAILER_SCOPE_VIOLATION": "The acting retailer does not own the target resource.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this user from deciding this review track.",
    "ERR_WAIVE_NOT_PERMITTED": "Only a ShelfAdmin may waive a BLOCKING rejection error.",
    "ERR_INVALID_PAGINATION": "limit must be an integer in 1..100 and offset an integer >= 0.",
    "ERR_INVALID_REQUEST": "The request body is invalid.",
    "ERR_WINDOW_INVALID": "window_end must be strictly after window_start and both must be ISO-8601 instants.",
    "ERR_STALE_VERSION": "The supplied expected version does not match the current version of the parent row.",
}
