"""Error catalog: error_id -> default HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                      # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_STALE_BOOKING_VERSION = "ERR_STALE_BOOKING_VERSION"        # 412
ERR_STALE_CHAIR_SLOT_VERSION = "ERR_STALE_CHAIR_SLOT_VERSION"  # 412
ERR_THERAPIST_DAILY_CAP = "ERR_THERAPIST_DAILY_CAP"            # 422
ERR_LICENSE_INVALID = "ERR_LICENSE_INVALID"                    # 422
ERR_THERAPIST_DOUBLE_BOOKED = "ERR_THERAPIST_DOUBLE_BOOKED"    # 422
ERR_SIGNUP_SHEET_FULL = "ERR_SIGNUP_SHEET_FULL"                # 422
ERR_DUPLICATE_SIGNUP = "ERR_DUPLICATE_SIGNUP"                  # 422
ERR_WAIVER_MISSING = "ERR_WAIVER_MISSING"                      # 422
ERR_CREDIT_LIMIT_EXCEEDED = "ERR_CREDIT_LIMIT_EXCEEDED"        # 422
ERR_LIVE_INVOICE_EXISTS = "ERR_LIVE_INVOICE_EXISTS"            # 422
ERR_DUPLICATE_SURVEY = "ERR_DUPLICATE_SURVEY"                  # 422
ERR_WINDOW_NOT_DIVISIBLE = "ERR_WINDOW_NOT_DIVISIBLE"          # 422
ERR_ACCOUNT_SUSPENDED = "ERR_ACCOUNT_SUSPENDED"                # 422
ERR_REGION_INACTIVE = "ERR_REGION_INACTIVE"                    # 422
ERR_BOOKING_NOT_COMPLETED = "ERR_BOOKING_NOT_COMPLETED"        # 422
ERR_CLAIMS_OUTSTANDING = "ERR_CLAIMS_OUTSTANDING"              # 422
ERR_DISPUTE_REASON_REQUIRED = "ERR_DISPUTE_REASON_REQUIRED"    # 400


def unauthenticated(msg="Missing or empty X-User-Role / X-User-ID headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Role not permitted for this endpoint"):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="Path id references a non-existent entity"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Malformed field"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def invalid_state(msg="Target entity not in a state from which the requested transition is permitted"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def unprocessable(error_id, msg):
    return ApiError(error_id, 422, msg)
