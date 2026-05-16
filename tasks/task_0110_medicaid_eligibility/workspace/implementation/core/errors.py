"""Error catalog and APIError exception (PRD §5)."""


class APIError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error ID -> HTTP status (per SCAFFOLD 1.6 / PRD §5)
ERRORS = {
    "ERR_INVALID_REQUEST": 400,
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_FORBIDDEN_SAME_ACTOR": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_HOUSEHOLD_INCOMPLETE": 409,
    "ERR_APPEAL_WINDOW_EXPIRED": 409,
    "ERR_APPEAL_ALREADY_EXISTS": 409,
    "ERR_HEARING_CONFLICT": 409,
    "ERR_HEARING_NOT_DUE": 409,
    "ERR_ENROLLMENT_OVERLAP": 409,
    "ERR_NOT_ELIGIBLE": 422,
    "ERR_FPL_THRESHOLD_INVALID": 422,
}


def raise_error(error_id: str, message: str = ""):
    http = ERRORS.get(error_id, 500)
    raise APIError(error_id, message or error_id, http)
