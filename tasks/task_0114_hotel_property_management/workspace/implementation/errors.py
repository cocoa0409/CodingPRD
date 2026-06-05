"""Error catalogue and the ApiError exception.

Every error_id / HTTP status pair is read verbatim from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id -> http status (PRD §5 Error Code Catalogue)
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 422,
    "ERR_INVALID_REQUEST": 400,
    "ERR_HOTEL_AUDIT_LOCKED": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_RATE_PLAN_MISMATCH": 409,
    "ERR_ROOM_NOT_ASSIGNABLE": 409,
    "ERR_BLOCK_CUTOFF_PASSED": 409,
    "ERR_BLOCK_HAS_PENDING_PICKUPS": 409,
    "ERR_NO_AVAILABILITY": 409,
    "ERR_CREDIT_LIMIT_EXCEEDED": 402,
    "ERR_CORPORATE_SUSPENDED": 409,
    "ERR_ROOM_NOT_INSPECTED": 409,
    "ERR_NO_ROOM_ASSIGNED": 409,
    "ERR_FOLIO_NOT_OPEN": 409,
    "ERR_FOLIO_DISPUTED_CHECKOUT": 409,
    "ERR_AUDIT_BLOCKED_OPEN_BALANCE": 409,
    "ERR_AUDIT_ALREADY_RUNNING": 409,
    "ERR_ARRIVAL_NOT_REACHED": 409,
    "ERR_STALE_ROOM_VERSION": 412,
    "ERR_STALE_BLOCK_VERSION": 412,
    "ERR_STALE_VERSION": 412,
    "ERR_DUPLICATE_RESOURCE": 409,
    "ERR_PAGINATION_INVALID": 400,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
