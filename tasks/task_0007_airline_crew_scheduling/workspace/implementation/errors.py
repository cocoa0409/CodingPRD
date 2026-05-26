"""Domain errors. error_id strings and their HTTP status come from PRD §5."""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message
        super().__init__(message)


# Error ids (PRD §5)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_CROSS_ENTITY_STATE = "ERR_CROSS_ENTITY_STATE"
ERR_FAA_DUTY_CAP_EXCEEDED = "ERR_FAA_DUTY_CAP_EXCEEDED"
ERR_FAA_FLIGHT_CAP_EXCEEDED = "ERR_FAA_FLIGHT_CAP_EXCEEDED"
ERR_CREW_REST_VIOLATION = "ERR_CREW_REST_VIOLATION"
ERR_RANK_SEAT_MISMATCH = "ERR_RANK_SEAT_MISMATCH"
ERR_INVALID_TIME_WINDOW = "ERR_INVALID_TIME_WINDOW"
ERR_PAIRING_OVERLAP = "ERR_PAIRING_OVERLAP"
ERR_LEG_OVERLAP = "ERR_LEG_OVERLAP"
ERR_DUPLICATE_BID = "ERR_DUPLICATE_BID"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_NO_RESERVE_AVAILABLE = "ERR_NO_RESERVE_AVAILABLE"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"


def unauthenticated(msg="Missing or empty auth headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Caller not authorized"):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_state(msg="Invalid state transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def cross_entity_state(msg="Dependent entity in incompatible state"):
    return ApiError(ERR_CROSS_ENTITY_STATE, 409, msg)


def faa_duty_cap(msg="FAA duty cap exceeded"):
    return ApiError(ERR_FAA_DUTY_CAP_EXCEEDED, 422, msg)


def faa_flight_cap(msg="FAA flight cap exceeded"):
    return ApiError(ERR_FAA_FLIGHT_CAP_EXCEEDED, 422, msg)


def crew_rest_violation(msg="Crew rest interval below threshold"):
    return ApiError(ERR_CREW_REST_VIOLATION, 422, msg)


def rank_seat_mismatch(msg="Rank and seat incompatible"):
    return ApiError(ERR_RANK_SEAT_MISMATCH, 422, msg)


def invalid_time_window(msg="Invalid time window"):
    return ApiError(ERR_INVALID_TIME_WINDOW, 422, msg)


def pairing_overlap(msg="Pairing duty windows overlap"):
    return ApiError(ERR_PAIRING_OVERLAP, 422, msg)


def leg_overlap(msg="Flight legs overlap"):
    return ApiError(ERR_LEG_OVERLAP, 422, msg)


def duplicate_bid(msg="Bid already exists"):
    return ApiError(ERR_DUPLICATE_BID, 409, msg)


def stale_version(msg="Expected version does not match current version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def no_reserve_available(msg="No reserve crew available"):
    return ApiError(ERR_NO_RESERVE_AVAILABLE, 422, msg)


def invalid_request(msg="Invalid request"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)
