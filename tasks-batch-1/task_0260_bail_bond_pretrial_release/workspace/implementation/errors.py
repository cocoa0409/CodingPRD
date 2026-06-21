"""Error catalogue and the ApiError exception carrier.

Error IDs and HTTP statuses come verbatim from SCAFFOLD §1.6 / PRD §5.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# (error_id -> http_status) catalogue
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE_CASE_NUMBER": 409,
    "ERR_DUPLICATE_SERIAL": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_BOND_TYPE_NOT_ALLOWED": 409,
    "ERR_GPS_NOT_REQUIRED": 409,
    "ERR_DOCKET_OVERLAP": 409,
    "ERR_DEVICE_SLOT_OCCUPIED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_GRACE_EXPIRED": 409,
    "ERR_GRACE_NOT_EXPIRED": 409,
    "ERR_TIMING_VIOLATION": 409,
    "ERR_INSUFFICIENT_INDEMNITY": 409,
    "ERR_INSUFFICIENT_COLLATERAL": 409,
    "ERR_CREDIT_LIMIT_EXCEEDED": 409,
    "ERR_INVALID_REMISSION": 400,
    "ERR_VALIDATION": 422,
}


def err(error_id, message=None):
    """Build an ApiError using the catalogued HTTP status for error_id."""
    return ApiError(error_id, ERRORS[error_id], message)
