"""Custom error class and the full error catalogue (PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue: error_id -> http_status (PRD §5 / scaffold §1.6)
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_RFQ_NO_PART_LINES": 409,
    "ERR_RFQ_NOT_SUBMITTED": 409,
    "ERR_RFQ_HAS_APPROVED_QUOTE": 409,
    "ERR_QUOTE_NO_ROUTING": 409,
    "ERR_QUOTE_NOT_APPROVED": 409,
    "ERR_MATERIAL_NOT_ALLOCATED": 409,
    "ERR_INSUFFICIENT_MATERIAL": 409,
    "ERR_INVALID_QTY_STARTED": 409,
    "ERR_SLOT_CONFLICT": 409,
    "ERR_STATION_CONFLICT": 409,
    "ERR_STATION_MODE_UNSUPPORTED": 409,
    "ERR_WO_NOT_IN_PROCESS": 409,
    "ERR_INSPECTION_MODE_REQUIRED": 409,
    "ERR_DISPOSITION_QTY_MISMATCH": 409,
    "ERR_DISPOSITION_EXCEEDS_WIP": 409,
    "ERR_MISSING_ACTUAL_CYCLE": 409,
    "ERR_WO_ALREADY_INSPECTED": 409,
    "ERR_SHIPMENT_HAS_INVOICE": 409,
    "ERR_INVOICE_UNPAID": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_CATALOG[error_id], message)
