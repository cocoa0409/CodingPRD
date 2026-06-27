"""Error classes and error-id constants for the DPC API."""


class ApiError(Exception):
    """Carries an error_id, human message, and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (PRD §5 / scaffold §1.6)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"        # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                    # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                    # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"        # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"            # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"            # 412
ERR_MEMBER_NOT_ELIGIBLE = "ERR_MEMBER_NOT_ELIGIBLE"  # 409
ERR_SLOT_UNAVAILABLE = "ERR_SLOT_UNAVAILABLE"      # 409
ERR_MEMBER_DOUBLE_BOOKED = "ERR_MEMBER_DOUBLE_BOOKED"  # 409
ERR_PHYSICAL_NOT_DUE = "ERR_PHYSICAL_NOT_DUE"      # 409
ERR_NO_PANEL_CAPACITY = "ERR_NO_PANEL_CAPACITY"    # 409
ERR_SEAT_LIMIT_REACHED = "ERR_SEAT_LIMIT_REACHED"  # 409
ERR_CARE_PLAN_EMPTY = "ERR_CARE_PLAN_EMPTY"        # 409
ERR_REFERRAL_EXPIRED = "ERR_REFERRAL_EXPIRED"      # 409
ERR_AMOUNT_MISMATCH = "ERR_AMOUNT_MISMATCH"        # 422
ERR_PCP_REQUIRED = "ERR_PCP_REQUIRED"              # 409
ERR_VALIDATION = "ERR_VALIDATION"                  # 422


def unauthenticated(msg=None):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg=None):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg=None):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg=None):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def invalid_state(msg=None):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def stale_version(msg=None):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def member_not_eligible(msg=None):
    return ApiError(ERR_MEMBER_NOT_ELIGIBLE, 409, msg)


def slot_unavailable(msg=None):
    return ApiError(ERR_SLOT_UNAVAILABLE, 409, msg)


def member_double_booked(msg=None):
    return ApiError(ERR_MEMBER_DOUBLE_BOOKED, 409, msg)


def physical_not_due(msg=None):
    return ApiError(ERR_PHYSICAL_NOT_DUE, 409, msg)


def no_panel_capacity(msg=None):
    return ApiError(ERR_NO_PANEL_CAPACITY, 409, msg)


def seat_limit_reached(msg=None):
    return ApiError(ERR_SEAT_LIMIT_REACHED, 409, msg)


def care_plan_empty(msg=None):
    return ApiError(ERR_CARE_PLAN_EMPTY, 409, msg)


def referral_expired(msg=None):
    return ApiError(ERR_REFERRAL_EXPIRED, 409, msg)


def amount_mismatch(msg=None):
    return ApiError(ERR_AMOUNT_MISMATCH, 422, msg)


def pcp_required(msg=None):
    return ApiError(ERR_PCP_REQUIRED, 409, msg)


def validation(msg=None):
    return ApiError(ERR_VALIDATION, 422, msg)
