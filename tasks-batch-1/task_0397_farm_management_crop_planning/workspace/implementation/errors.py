"""Error classes and error-id constants.

Every error_id and its HTTP status is taken verbatim from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Catalog (error_id -> http_status) verbatim from PRD §5 ---
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_PARCEL_NOT_AVAILABLE": 409,
    "ERR_PLANNED_ACRES_EXCEED_PARCEL": 409,
    "ERR_STALE_PARCEL_VERSION": 412,
    "ERR_PLAN_ALREADY_PLANTED": 409,
    "ERR_NO_PLANTING_RECORDED": 409,
    "ERR_NO_HARVEST_RECORDED": 409,
    "ERR_PLAN_NOT_GROWING": 409,
    "ERR_APPLICATOR_NOT_CERTIFIED": 409,
    "ERR_APPLICATOR_MISMATCH": 409,
    "ERR_REENTRY_INTERVAL_ACTIVE": 409,
    "ERR_PREHARVEST_INTERVAL_ACTIVE": 409,
    "ERR_SEASONAL_RATE_EXCEEDED": 409,
    "ERR_PRODUCT_CATEGORY_MISMATCH": 409,
    "ERR_INSUFFICIENT_INVENTORY": 409,
    "ERR_EQUIPMENT_WINDOW_CONFLICT": 409,
    "ERR_EQUIPMENT_DOWN": 409,
    "ERR_IRRIGATION_WINDOW_CONFLICT": 409,
    "ERR_IRRIGATION_NOT_DUE": 409,
    "ERR_LOT_QUALITY_INSUFFICIENT": 409,
    "ERR_LOT_ALREADY_GRADED": 409,
    "ERR_LOT_ALREADY_COMMITTED": 409,
    "ERR_CROP_MISMATCH": 409,
    "ERR_CONTRACT_OVERCOMMIT": 409,
    "ERR_CONTRACT_NOT_FILLED": 409,
    "ERR_VALIDATION_WINDOW_INVALID": 400,
}


def err(error_id, message=None):
    """Build an ApiError from the catalog so the http_status is always consistent."""
    return ApiError(error_id, ERROR_CATALOG[error_id], message)
