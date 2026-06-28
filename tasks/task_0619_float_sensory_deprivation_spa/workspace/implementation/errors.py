"""Error catalog. error_id values + HTTP status from SCAFFOLD §1.6 / PRD §5."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Convenience constructors keyed to the catalog.
def unauthenticated(msg="Missing or unrecognized authentication headers."):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden(msg="Role not permitted, or member acting on a resource it does not own."):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def not_found(msg="Resource not found."):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_request(msg="Malformed request body."):
    return ApiError("ERR_INVALID_REQUEST", 422, msg)


def validation_range(msg="Numeric field out of range."):
    return ApiError("ERR_VALIDATION_RANGE", 422, msg)


def tank_kind_mismatch(msg="Tank kind / pay-source combination invalid."):
    return ApiError("ERR_TANK_KIND_MISMATCH", 422, msg)


def invalid_state(msg="Requested transition not defined from the resource's current state."):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def plan_inactive(msg="Membership plan is inactive."):
    return ApiError("ERR_PLAN_INACTIVE", 409, msg)


def gift_card_inactive(msg="Gift card is VOID or DEPLETED."):
    return ApiError("ERR_GIFT_CARD_INACTIVE", 409, msg)


def tank_has_bookings(msg="Tank still has active bookings."):
    return ApiError("ERR_TANK_HAS_BOOKINGS", 409, msg)


def tank_unavailable(msg="Tank not CLEAN and IN_SERVICE."):
    return ApiError("ERR_TANK_UNAVAILABLE", 409, msg)


def member_not_eligible(msg="Member not eligible to confirm."):
    return ApiError("ERR_MEMBER_NOT_ELIGIBLE", 409, msg)


def tank_time_conflict(msg="Booking window overlaps another active booking on the tank."):
    return ApiError("ERR_TANK_TIME_CONFLICT", 409, msg)


def attendant_time_conflict(msg="Orientation overlaps another scheduled orientation on the attendant."):
    return ApiError("ERR_ATTENDANT_TIME_CONFLICT", 409, msg)


def insufficient_funds(msg="Not enough credits or gift-card balance."):
    return ApiError("ERR_INSUFFICIENT_FUNDS", 402, msg)


def timing_not_allowed(msg="Action attempted outside its allowed time window."):
    return ApiError("ERR_TIMING_NOT_ALLOWED", 409, msg)


def stale_version(msg="expected_membership_version does not match current version."):
    return ApiError("ERR_STALE_VERSION", 412, msg)
