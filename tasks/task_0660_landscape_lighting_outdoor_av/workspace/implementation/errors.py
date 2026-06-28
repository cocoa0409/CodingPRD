"""Error catalogue (PRD Section 5 / SCAFFOLD §1.6).

Each ApiError carries an error_id, a human-readable message, and an HTTP status.
The error response body uses the exact field names from the response envelope:
data.error_id and data.message.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status for each error_id (PRD Section 5 Error Code Catalogue).
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CROSS_PROJECT_REFERENCE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_TRANSFORMER_VERSION": 412,
    "ERR_WIRING_NOT_COMPLETE": 409,
    "ERR_UNZONED_FIXTURE": 409,
    "ERR_VISIT_WINDOW_OVERLAP": 409,
    "ERR_SCENE_WINDOW_TOO_CLOSE": 409,
    "ERR_TRANSFORMER_CAPACITY_EXCEEDED": 409,
    "ERR_OUT_OF_WARRANTY": 409,
    "ERR_INVALID_WINDOW": 400,
    "ERR_DEMO_TIME_REQUIRED": 400,
    "ERR_DUPLICATE_EMAIL": 409,
    "ERR_TRANSFORMER_NOT_ENERGIZED": 409,
    "ERR_QUOTE_NO_LINES": 409,
    "ERR_DESIGN_NOT_LOCKED": 409,
    "ERR_PROJECT_NOT_INSTALLED": 409,
    "ERR_QUOTE_EXPIRED": 409,
    "ERR_ROUTE_DATE_MISMATCH": 409,
    "ERR_PLAN_BLOCKS_CLOSE": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP[error_id], message)
