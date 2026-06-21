"""Error catalogue (PRD §5) and the ApiError exception type.

Every error_id and HTTP status here is read verbatim from the PRD §5 / SCAFFOLD §1.6
error catalogue. No status is assumed.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id -> http_status (PRD §5 Error Code Catalogue)
ERROR_STATUS = {
    "ERR_MISSING_AUTH_CONTEXT": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_BOX_NOT_FOUND": 404,
    "ERR_REQUEST_NOT_FOUND": 404,
    "ERR_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_ORDER_NOT_SCHEDULED": 409,
    "ERR_ORDER_NOT_EN_ROUTE": 409,
    "ERR_ORDER_NOT_DROP_OFF_READY": 409,
    "ERR_ORDER_NOT_PICKED_UP": 409,
    "ERR_ORDER_NOT_AT_PLANT": 409,
    "ERR_ORDER_NOT_CANCELLABLE": 409,
    "ERR_DISPATCH_NOT_APPLICABLE": 409,
    "ERR_MODE_NOT_ON_SITE": 409,
    "ERR_MODE_NOT_OFF_SITE": 409,
    "ERR_MODE_NOT_DROP_OFF": 409,
    "ERR_WEIGH_IN_REQUIRED": 409,
    "ERR_CERTIFICATE_ALREADY_ISSUED": 409,
    "ERR_SUBJECT_ON_HOLD": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_RETENTION_NOT_ELAPSED": 409,
    "ERR_SLOT_CONFLICT": 409,
    "ERR_ONSITE_BUFFER_CONFLICT": 409,
    "ERR_BOX_NOT_INGESTED": 409,
    "ERR_BOX_NOT_STORED": 409,
    "ERR_BOX_NOT_OUT": 409,
    "ERR_REQUEST_NOT_PENDING": 409,
    "ERR_REQUEST_NOT_DELIVERED": 409,
    "ERR_RETURN_NOT_PENDING": 409,
    "ERR_REQUEST_NOT_CANCELLABLE": 409,
    "ERR_HOLD_NOT_ACTIVE": 409,
    "ERR_ACCOUNT_NOT_ACTIVE": 409,
    "ERR_ACCOUNT_NOT_SUSPENDED": 409,
    "ERR_ACCOUNT_NOT_CLOSABLE": 409,
    "ERR_OUTSTANDING_BOXES": 409,
    "ERR_OUTSTANDING_ORDERS": 409,
    "ERR_CONTAINER_LOCATION_MISMATCH": 409,
    "ERR_DUPLICATE_BARCODE": 409,
    "ERR_INVALID_FIELD_VALUE": 422,
    "ERR_NO_ACTIVE_RATE_CARD": 409,
}


def err(error_id, message=None):
    """Construct an ApiError, looking up the HTTP status from the catalogue."""
    return ApiError(error_id, ERROR_STATUS[error_id], message)
