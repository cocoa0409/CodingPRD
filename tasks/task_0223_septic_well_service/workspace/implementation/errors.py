"""Error catalog and the ApiError exception type.

Error IDs and HTTP statuses are taken verbatim from SCAFFOLD.yaml §1.6 and
PRD §5.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: id -> http status
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 422,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_IMMUTABLE": 409,
    "ERR_ROUTE_LOCKED": 409,
    "ERR_ACCOUNT_ON_HOLD": 409,
    "ERR_TECH_SUSPENDED": 409,
    "ERR_TECH_NOT_CERTIFIED": 409,
    "ERR_TECH_WINDOW_CONFLICT": 409,
    "ERR_SITE_BUFFER_CONFLICT": 409,
    "ERR_OUTSIDE_SHIFT": 409,
    "ERR_REPORT_NOT_FINALIZED": 409,
    "ERR_SITE_NON_COMPLIANT": 409,
    "ERR_COOLING_OFF": 409,
    "ERR_MEASUREMENT_REQUIRED": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_VALIDATION": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)
