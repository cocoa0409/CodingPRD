"""Error classes and the canonical error catalog (PRD §5)."""


class APIError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Canonical error catalog: error_id -> http_status (from SCAFFOLD.yaml §1.6 / PRD §5).
ERROR_CATALOG = {
    "ERR_BAD_REQUEST": 400,
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_DMA_FROZEN": 409,
    "ERR_REVIEW_IN_PROGRESS": 409,
    "ERR_TOPOLOGY_ROLLBACK_BLOCKED": 409,
    "ERR_DEVICE_UNMOUNTED": 409,
    "ERR_INVESTIGATION_NO_SIGNAL": 409,
    "ERR_DUPLICATE_READING": 200,  # idempotent replay returns 200
    "ERR_TOPOLOGY_DANGLING_REFERENCE": 422,
    "ERR_READING_TIMESTAMP_OUT_OF_RANGE": 422,
    "ERR_READING_OUT_OF_RANGE": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_INSUFFICIENT_DATA": 422,
    "ERR_DEVICE_CONFIG_INVALID": 422,
    "ERR_WORK_ORDER_SEGMENT_MISSING": 422,
}


def err(error_id: str, message: str = "") -> APIError:
    return APIError(error_id, message or error_id, ERROR_CATALOG[error_id])
