"""Error catalogue and the ApiError exception.

HTTP status codes come from PRD §5 (Error Code Catalogue) / SCAFFOLD errors table.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- HTTP status per error id (PRD §5) ---
ERROR_STATUS = {
    # Auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_INVALID_REQUEST": 400,
    # Not found
    "ERR_CLIENT_NOT_FOUND": 404,
    "ERR_SKU_NOT_FOUND": 404,
    "ERR_BIN_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_RECEIPT_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_WAVE_NOT_FOUND": 404,
    "ERR_PICK_TASK_NOT_FOUND": 404,
    "ERR_CARTON_NOT_FOUND": 404,
    "ERR_SHIPMENT_NOT_FOUND": 404,
    "ERR_RETURN_NOT_FOUND": 404,
    "ERR_CYCLE_COUNT_NOT_FOUND": 404,
    "ERR_CHARGE_NOT_FOUND": 404,
    # State
    "ERR_RECEIPT_NOT_ANNOUNCED": 409,
    "ERR_RECEIPT_NOT_RECEIVED": 409,
    "ERR_WAVE_NOT_BUILDING": 409,
    "ERR_WAVE_EMPTY": 409,
    "ERR_ORDER_NOT_IMPORTED": 409,
    "ERR_ORDER_NOT_PICKING": 409,
    "ERR_ORDER_NOT_PACKED": 409,
    "ERR_ORDER_NOT_SHIPPED": 409,
    "ERR_ORDER_NOT_CANCELLABLE": 409,
    "ERR_PICKS_INCOMPLETE": 409,
    "ERR_NOT_SHORT": 409,
    "ERR_PICK_NOT_ASSIGNED": 409,
    "ERR_LABEL_REQUIRED": 409,
    "ERR_SHIPMENT_NOT_LABELLED": 409,
    "ERR_RETURN_NOT_REQUESTED": 409,
    "ERR_RETURN_NOT_GRADED": 409,
    "ERR_STALE_LOT_VERSION": 412,
    # Business
    "ERR_CLIENT_SUSPENDED": 409,
    "ERR_SKU_DISCONTINUED": 409,
    "ERR_CLIENT_OWNERSHIP_MISMATCH": 409,
    "ERR_BIN_BLOCKED": 409,
    "ERR_BIN_CAPACITY_EXCEEDED": 409,
    "ERR_PALLET_OCCUPIED_BY_OTHER_CLIENT": 409,
    "ERR_PACK_UNIT_MISMATCH": 409,
    "ERR_CARTON_OVERFLOW": 409,
    "ERR_INSUFFICIENT_INVENTORY": 409,
    "ERR_HAZMAT_CARRIER_FORBIDDEN": 409,
    "ERR_RETURN_QTY_EXCEEDS_SHIPPED": 409,
}


def err(error_id, message=None):
    """Build an ApiError, resolving HTTP status from the catalogue."""
    return ApiError(error_id, ERROR_STATUS.get(error_id, 400), message)
