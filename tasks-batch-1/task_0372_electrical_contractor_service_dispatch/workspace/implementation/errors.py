"""Error catalog and the ApiError exception class.

Every error_id and HTTP status is taken verbatim from PRD §5 / SCAFFOLD errors[].
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (PRD §5 / SCAFFOLD Table 6). Maps error_id -> http_status.
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_LICENSE_INSUFFICIENT": 409,
    "ERR_TECH_NOT_ON_CALL": 409,
    "ERR_ZONE_MISMATCH": 409,
    "ERR_TECH_DOUBLE_BOOKED": 409,
    "ERR_PERMIT_NOT_PASSED": 409,
    "ERR_INSUFFICIENT_STOCK": 409,
    "ERR_ALREADY_INVOICED": 409,
    "ERR_OPEN_CALLBACK": 409,
    "ERR_NOT_WARRANTY_COVERED": 409,
    "ERR_DUPLICATE": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
