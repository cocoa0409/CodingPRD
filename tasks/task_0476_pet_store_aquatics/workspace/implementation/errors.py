"""Error catalogue (PRD §5) and the ApiError exception type."""


class ApiError(Exception):
    """A business/validation error carrying error_id, message, http_status.

    The error_id and http_status come verbatim from the PRD §5 error catalogue.
    """

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status codes per PRD §5 Error Code Catalogue.
ERROR_HTTP = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 401,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_STORE_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_BATCH_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_PRESCRIPTION_NOT_FOUND": 404,
    "ERR_APPOINTMENT_NOT_FOUND": 404,
    "ERR_SUBSCRIPTION_NOT_FOUND": 404,
    "ERR_SHIPMENT_NOT_FOUND": 404,
    "ERR_SPECIAL_ORDER_NOT_FOUND": 404,
    "ERR_EVENT_NOT_FOUND": 404,
    "ERR_PLACEMENT_NOT_FOUND": 404,
    "ERR_RECALL_NOT_FOUND": 404,
    "ERR_INVALID_FIELD_VALUE": 422,
    "ERR_DUPLICATE_RESOURCE": 409,
    "ERR_BATCH_HEALTH_STATE_INVALID": 409,
    "ERR_BATCH_SALE_STATE_INVALID": 409,
    "ERR_SUBSCRIPTION_STATE_INVALID": 409,
    "ERR_SPECIAL_ORDER_STATE_INVALID": 409,
    "ERR_APPOINTMENT_STATE_INVALID": 409,
    "ERR_EVENT_STATE_INVALID": 409,
    "ERR_RECALL_STATE_INVALID": 409,
    "ERR_PLACEMENT_NOT_RETURNABLE": 409,
    "ERR_ROOM_DOUBLE_BOOKED": 409,
    "ERR_QUARANTINE_NOT_ELAPSED": 409,
    "ERR_APPOINTMENT_NOT_STARTED": 409,
    "ERR_APPOINTMENT_NOT_ENDED": 409,
    "ERR_SHIPMENT_NOT_DUE": 409,
    "ERR_BATCH_NOT_HEALTHY": 409,
    "ERR_QUARANTINE_MORTALITY_BLOCK": 409,
    "ERR_PRODUCT_RECALLED": 409,
    "ERR_PRESCRIPTION_REQUIRED": 409,
    "ERR_APPOINTMENT_NOT_ELIGIBLE": 409,
    "ERR_INSUFFICIENT_HEAD": 409,
    "ERR_EVENT_CAPACITY_EXCEEDED": 409,
    "ERR_INSUFFICIENT_INVENTORY": 409,
    "ERR_INSUFFICIENT_LOYALTY_POINTS": 409,
    "ERR_STALE_VERSION": 412,
}


def err(error_id, message=None):
    """Construct an ApiError using the catalogue's HTTP status for error_id."""
    return ApiError(error_id, ERROR_HTTP[error_id], message)
