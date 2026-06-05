"""Error catalog and the ApiError exception type.

Each error carries error_id (machine-readable), an HTTP status, and a
human-readable message. The error_id / http pairs are taken verbatim from the
PRD §5 Error Code Catalogue and SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Catalog: error_id -> http_status
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_CLASS_MISMATCH": 409,
    "ERR_VEHICLE_NOT_AVAILABLE": 409,
    "ERR_MEMBER_BLOCKED": 409,
    "ERR_WITHIN_GRACE": 409,
    "ERR_GRACE_WINDOW_EXPIRED": 409,
    "ERR_ODOMETER_ROLLBACK": 409,
    "ERR_TOTAL_LOSS_REQUIRES_WRITEOFF": 409,
    "ERR_NO_TOTAL_INCIDENT": 409,
    "ERR_NO_AVAILABILITY": 409,
    "ERR_AGREEMENT_STILL_OPEN": 409,
    "ERR_OPEN_INCIDENT": 409,
    "ERR_NOT_AN_UPGRADE": 409,
    "ERR_INSUFFICIENT_POINTS": 409,
    "ERR_VEHICLE_DOUBLE_BOOKED": 409,
    "ERR_LOCATION_CLASS_CAPACITY": 409,
}


def err(error_id, message=None):
    """Convenience constructor that looks up the HTTP status from the catalog."""
    return ApiError(error_id, ERROR_CATALOG[error_id], message)
