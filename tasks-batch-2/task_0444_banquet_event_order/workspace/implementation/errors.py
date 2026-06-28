"""Error catalog (§1.6 / PRD §5). Each error carries an id, HTTP status, message."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error constructors keyed to the catalog -------------------------------
def unauthenticated(msg="Missing or unknown X-User-Role / X-User-ID header"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden(msg="Acting role is not permitted for this operation"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_request(msg="Malformed, incomplete, mistyped, or out-of-range request body"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def invalid_state(msg="Target resource is not in a valid state for the requested transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def stale_version(msg="expected_event_version does not match the event's current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def room_double_booked(msg="make-definite would overlap another DEFINITE booking once the buffer is applied"):
    return ApiError("ERR_ROOM_DOUBLE_BOOKED", 409, msg)


def capacity_exceeded(msg="Effective room capacity is below billable_count"):
    return ApiError("ERR_CAPACITY_EXCEEDED", 409, msg)


def pricing_mode_field_mismatch(msg="CONSUMPTION line missing consumption_qty, or PER_PERSON line supplied it"):
    return ApiError("ERR_PRICING_MODE_FIELD_MISMATCH", 422, msg)


def pickup_exceeds_reserved(msg="rooms_picked_up outside [0, rooms_reserved]"):
    return ApiError("ERR_PICKUP_EXCEEDS_RESERVED", 422, msg)


def block_insufficient_rooms(msg="rooms_reserved exceeds the block's available rooms on a night in range"):
    return ApiError("ERR_BLOCK_INSUFFICIENT_ROOMS", 409, msg)


def deposit_unsettled(msg="The deposit milestone (sequence_no==1) is not settled"):
    return ApiError("ERR_DEPOSIT_UNSETTLED", 409, msg)


def deposit_locked(msg="void would unsettle the deposit milestone on a CONFIRMED event"):
    return ApiError("ERR_DEPOSIT_LOCKED", 409, msg)


def guarantee_required(msg="lock-guarantee requires a guarantee_count >= 1 in the body"):
    return ApiError("ERR_GUARANTEE_REQUIRED", 422, msg)


def no_bookings(msg="hold/confirm-space requires at least one non-RELEASED booking"):
    return ApiError("ERR_NO_BOOKINGS", 409, msg)


def booking_not_all_definite(msg="confirm-space requires every booking to be DEFINITE"):
    return ApiError("ERR_BOOKING_NOT_ALL_DEFINITE", 409, msg)


def event_terminal(msg="Mutation attempted on a COMPLETED or CANCELLED event"):
    return ApiError("ERR_EVENT_TERMINAL", 409, msg)


def validation_range(msg="A percentage field is outside its allowed range"):
    return ApiError("ERR_VALIDATION_RANGE", 422, msg)
