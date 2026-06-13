"""Error catalogue and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue (PRD §5 / scaffold §1.6)
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_SEASON_PHASE = ("ERR_SEASON_PHASE", 409)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_PLAYER_SUSPENDED = ("ERR_PLAYER_SUSPENDED", 409)
ERR_INVALID_MATCHUP = ("ERR_INVALID_MATCHUP", 409)
ERR_REFEREE_DOUBLE_BOOKED = ("ERR_REFEREE_DOUBLE_BOOKED", 409)
ERR_VENUE_DOUBLE_BOOKED = ("ERR_VENUE_DOUBLE_BOOKED", 409)
ERR_CAPACITY_EXCEEDED = ("ERR_CAPACITY_EXCEEDED", 409)
ERR_ROSTER_RULE = ("ERR_ROSTER_RULE", 409)
ERR_REFUND_EXCEEDS_FEE = ("ERR_REFUND_EXCEEDS_FEE", 409)
ERR_DUPLICATE = ("ERR_DUPLICATE", 409)
ERR_FEE_REQUIRED = ("ERR_FEE_REQUIRED", 409)
ERR_SCHEDULE_INCOMPLETE = ("ERR_SCHEDULE_INCOMPLETE", 409)
ERR_PAGINATION_RANGE = ("ERR_PAGINATION_RANGE", 422)


def err(code_tuple, message=None):
    error_id, http_status = code_tuple
    return ApiError(error_id, http_status, message)
