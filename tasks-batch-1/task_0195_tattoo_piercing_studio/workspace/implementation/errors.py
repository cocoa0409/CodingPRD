"""Error classes and the error-id -> HTTP-status catalog.

Every error_id and HTTP status is taken verbatim from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = ERROR_CATALOG.get(error_id, 400)


# error_id -> http status code
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_CLIENT_NOT_VERIFIED": 422,
    "ERR_UNDERAGE": 422,
    "ERR_WAIVER_MISSING": 422,
    "ERR_INVALID_PRICING": 422,
    "ERR_REQUEST_NOT_APPROVED": 422,
    "ERR_INVALID_INTERVAL": 422,
    "ERR_ARTIST_DOUBLE_BOOKED": 409,
    "ERR_CHAIR_UNAVAILABLE": 409,
    "ERR_DEPOSIT_NOT_PAYABLE": 422,
    "ERR_DEPOSIT_NOT_MET": 422,
    "ERR_TOUCHUP_PARENT_NOT_COMPLETED": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_VALIDATION": 422,
}
