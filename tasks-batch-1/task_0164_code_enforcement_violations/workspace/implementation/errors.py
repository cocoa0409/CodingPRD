"""Error classes and the error catalog (PRD §5 / SCAFFOLD §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error id -> http status (PRD §5 catalogue).
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 422,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_NOT_NOTICE_OWNER": 403,
    "ERR_NO_SUBSTANTIATION": 422,
    "ERR_FEE_SCHEDULE_MISSING": 422,
    "ERR_DEMOLITION_NOT_PERMITTED": 422,
    "ERR_CONTEST_WINDOW_CLOSED": 422,
    "ERR_HEARING_NOT_RIPE": 422,
    "ERR_CONTINUANCE_LIMIT": 422,
    "ERR_FORECLOSURE_NOT_RIPE": 422,
    "ERR_LIEN_ALREADY_EXISTS": 409,
    "ERR_NOTHING_TO_LIEN": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_BALANCE_OUTSTANDING": 409,
    "ERR_MISSING_ACTUAL_COST": 422,
    "ERR_DUPLICATE_PARCEL": 409,
    "ERR_REINSPECTION_TARGET_INVALID": 422,
    "ERR_PROPERTY_HAS_OPEN_CASE": 409,
    "ERR_HEARING_SLOT_CONFLICT": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)
