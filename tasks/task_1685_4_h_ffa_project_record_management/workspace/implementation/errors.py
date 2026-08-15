"""Error catalogue (PRD section 5) and the API error exception type."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_FORBIDDEN = "ERR_FORBIDDEN"                      # 403
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"              # 412
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"  # 422
ERR_SCREENING_NOT_CLEARED = "ERR_SCREENING_NOT_CLEARED"  # 422
ERR_ROOM_CONFLICT = "ERR_ROOM_CONFLICT"              # 409
ERR_PEN_CAPACITY_EXCEEDED = "ERR_PEN_CAPACITY_EXCEEDED"  # 422
ERR_STAR_QUOTA_EXCEEDED = "ERR_STAR_QUOTA_EXCEEDED"  # 422
ERR_OWNERSHIP_PERIOD_SHORT = "ERR_OWNERSHIP_PERIOD_SHORT"  # 422
ERR_INSUFFICIENT_TREASURY = "ERR_INSUFFICIENT_TREASURY"  # 422
ERR_REFERENTIAL_INTEGRITY = "ERR_REFERENTIAL_INTEGRITY"  # 422


def not_found(message="A referenced resource id does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, message)


def invalid_request(message):
    return ApiError(ERR_INVALID_REQUEST, 400, message)


def invalid_state(message):
    return ApiError(ERR_INVALID_STATE, 409, message)
