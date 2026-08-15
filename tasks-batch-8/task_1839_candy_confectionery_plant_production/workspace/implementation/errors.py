"""Error catalog: every error id with its HTTP status, plus the ApiError
exception carrying error_id / message / http_status."""


ERROR_HTTP_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_LINE_NOT_AVAILABLE": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_SWAB_FAILED": 422,
    "ERR_ALLERGEN_WASH_REQUIRED": 422,
    "ERR_UNDECLARED_ALLERGEN": 422,
    "ERR_MOLD_SHAPE_MISMATCH": 422,
    "ERR_MOLD_NOT_AVAILABLE": 409,
    "ERR_LINE_SCHEDULE_CONFLICT": 409,
    "ERR_WINDOW_OVERLAP": 409,
    "ERR_GIFT_CYCLE": 422,
    "ERR_WINDOW_DATE_ORDER": 422,
    "ERR_OUTSIDE_PRODUCTION_WINDOW": 422,
    "ERR_PREMATURE_CLOSE": 422,
    "ERR_PO_NOT_DUE": 422,
    "ERR_LOT_EXPIRED": 422,
    "ERR_PACKAGING_SHORTAGE": 422,
    "ERR_INSUFFICIENT_COMPONENT_LOTS": 422,
    "ERR_REWORK_QTY_EXCEEDS_LOT": 422,
    "ERR_BLOOM_RELEASE_FORBIDDEN": 422,
    "ERR_LOT_NOT_REWORKABLE": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = ERROR_HTTP_STATUS[error_id]
        self.message = message
