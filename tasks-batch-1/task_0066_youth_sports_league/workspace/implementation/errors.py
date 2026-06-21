"""Error catalog and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http_status
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_FK_SCOPE_MISMATCH": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_REGISTRATION_WINDOW_CLOSED": 409,
    "ERR_AGE_OUT_OF_RANGE": 422,
    "ERR_NOT_YOUR_PICK": 409,
    "ERR_NOT_LAST_PICK": 409,
    "ERR_ROSTER_FULL": 409,
    "ERR_NO_REFEREE_CONFIRMED": 409,
    "ERR_REFEREE_TIME_CONFLICT": 409,
    "ERR_REFEREE_DAY_LIMIT": 409,
    "ERR_FIELD_SLOT_CONFLICT": 409,
    "ERR_TIE_NOT_ALLOWED": 422,
    "ERR_DUPLICATE_FAMILY_EMAIL": 409,
    "ERR_STALE_LEAGUE_VERSION": 412,
    "ERR_STALE_GAME_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)
