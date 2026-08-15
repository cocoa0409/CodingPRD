"""Error classes and error ID constants (from the PRD §5 error catalogue)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_FIELD_SEASON_CONFLICT = "ERR_FIELD_SEASON_CONFLICT"
ERR_KILN_WINDOW_OVERLAP = "ERR_KILN_WINDOW_OVERLAP"
ERR_MOISTURE_UNSAFE = "ERR_MOISTURE_UNSAFE"
ERR_WEIGHT_IMPOSSIBLE = "ERR_WEIGHT_IMPOSSIBLE"
ERR_LOT_NOT_DRIED = "ERR_LOT_NOT_DRIED"
ERR_MIXED_VARIETY = "ERR_MIXED_VARIETY"
ERR_MIXED_CROP_YEAR = "ERR_MIXED_CROP_YEAR"
ERR_DUPLICATE_FINAL_TEST = "ERR_DUPLICATE_FINAL_TEST"
ERR_PROVISIONAL_REQUIRED = "ERR_PROVISIONAL_REQUIRED"
ERR_FINAL_TEST_REQUIRED = "ERR_FINAL_TEST_REQUIRED"
ERR_CONTRACT_NOT_ACTIVE = "ERR_CONTRACT_NOT_ACTIVE"
ERR_SAMPLE_NOT_SELECTED = "ERR_SAMPLE_NOT_SELECTED"
ERR_CREDIT_LIMIT_EXCEEDED = "ERR_CREDIT_LIMIT_EXCEEDED"
ERR_EMPTY_DELIVERY = "ERR_EMPTY_DELIVERY"
ERR_ACREAGE_EXCEEDED = "ERR_ACREAGE_EXCEEDED"
ERR_DUPLICATE_CLAIM = "ERR_DUPLICATE_CLAIM"
ERR_PLAN_NOT_COMPLETE = "ERR_PLAN_NOT_COMPLETE"


def unauthenticated(msg="Missing or unrecognized authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Role not authorized for this endpoint"):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Invalid request"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def segregation_of_duties(msg="Caller may not act on a claim they filed"):
    return ApiError(ERR_SEGREGATION_OF_DUTIES, 403, msg)


def invalid_state(msg="Invalid state for this operation"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def stale_version(msg="Stale contract version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)
