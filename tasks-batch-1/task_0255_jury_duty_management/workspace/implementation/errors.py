"""Error catalog (PRD §5 / scaffold §1.6).

Every error_id maps to a fixed HTTP status. The ApiError carries the trio
(error_id, message, http_status) and is converted to the standard error
envelope by the app-level error handler.
"""

# Error IDs and their HTTP statuses (scaffold §1.6 / PRD §5).
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_DISPOSITION_ROLE_MISMATCH": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_TERM_NOT_OPEN": 409,
    "ERR_BEFORE_REPORT_DATE": 409,
    "ERR_DUPLICATE_SUMMONS": 409,
    "ERR_DUPLICATE_SERVICE_DATE": 409,
    "ERR_TRIAL_NOT_READY": 409,
    "ERR_SUMMONS_NOT_REPORTING": 409,
    "ERR_PANEL_FULL": 409,
    "ERR_DEFERRAL_LIMIT": 409,
    "ERR_POOL_EXHAUSTED": 409,
    "ERR_STALE_PANEL_VERSION": 412,
    "ERR_STALE_TERM_VERSION": 412,
    "ERR_INVALID_REQUEST": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message, http_status=None):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status if http_status is not None else ERROR_STATUS.get(error_id, 500)


def err(error_id, message):
    """Construct an ApiError using the catalog's HTTP status for error_id."""
    return ApiError(error_id, message, ERROR_STATUS.get(error_id, 500))
