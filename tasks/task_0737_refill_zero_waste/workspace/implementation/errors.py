"""Error catalog and the ApiError exception.

Every error_id maps to its HTTP status per PRD section 5 / SCAFFOLD section 1.6.
"""

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 400,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_STATION_NOT_FOUND": 404,
    "ERR_BIN_NOT_FOUND": 404,
    "ERR_CONTAINER_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_LINE_NOT_FOUND": 404,
    "ERR_RESTOCK_TASK_NOT_FOUND": 404,
    "ERR_SUBSCRIPTION_NOT_FOUND": 404,
    "ERR_VEHICLE_NOT_FOUND": 404,
    "ERR_DELIVERY_NOT_FOUND": 404,
    "ERR_INVALID_ORDER_STATE": 409,
    "ERR_INVALID_CONTAINER_STATE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_ALLERGEN_CONFLICT": 409,
    "ERR_BIN_QUARANTINED": 409,
    "ERR_CONTAINER_NOT_OWNED": 409,
    "ERR_STATION_SESSION_OVERLAP": 409,
    "ERR_VEHICLE_WINDOW_CONFLICT": 409,
    "ERR_EMPTY_ORDER": 422,
    "ERR_TARE_EXCEEDS_GROSS": 422,
    "ERR_INSUFFICIENT_STOCK": 409,
    "ERR_DELIVERY_ORDER_NOT_READY": 422,
    "ERR_DUPLICATE_EMAIL": 409,
    "ERR_STALE_VERSION": 412,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").title()
