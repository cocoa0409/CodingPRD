"""Error classes and error ID constants from the scaffold §1.6 error catalog."""


class ApiError(Exception):
    """Carries error_id, message, and http_status for the response envelope."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error ID -> default HTTP status (from §1.6 / PRD §5)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_CROSS_STATE_BLOCKED = "ERR_CROSS_STATE_BLOCKED"
ERR_WINGSPAN_EXCEEDED = "ERR_WINGSPAN_EXCEEDED"
ERR_GATE_WINDOW_CONFLICT = "ERR_GATE_WINDOW_CONFLICT"
ERR_CUTE_BUSY = "ERR_CUTE_BUSY"
ERR_EQUIPMENT_BUSY = "ERR_EQUIPMENT_BUSY"
ERR_REMOTE_STAND_FULL = "ERR_REMOTE_STAND_FULL"
ERR_SLOT_DOUBLE_BOOKED = "ERR_SLOT_DOUBLE_BOOKED"
ERR_TURN_TIME_TOO_SHORT = "ERR_TURN_TIME_TOO_SHORT"
ERR_SLOT_WINDOW_MISSED = "ERR_SLOT_WINDOW_MISSED"
ERR_STALE_GATE_VERSION = "ERR_STALE_GATE_VERSION"
ERR_VALIDATION = "ERR_VALIDATION"


def unauthenticated(msg="Missing or invalid authentication headers."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Role not permitted for this operation."):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_found(msg="Resource not found."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Malformed request body."):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def invalid_state(msg="Transition not legal from the current state."):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def cross_state_blocked(msg="Cross-state guard failed."):
    return ApiError(ERR_CROSS_STATE_BLOCKED, 409, msg)


def wingspan_exceeded(msg="Stand max wingspan is smaller than aircraft wingspan."):
    return ApiError(ERR_WINGSPAN_EXCEEDED, 422, msg)


def gate_window_conflict(msg="Gate window collides with an existing occupancy."):
    return ApiError(ERR_GATE_WINDOW_CONFLICT, 409, msg)


def cute_busy(msg="CUTE workstation already allocated for an overlapping window."):
    return ApiError(ERR_CUTE_BUSY, 409, msg)


def equipment_busy(msg="GSE asset cooldown/exclusivity violated."):
    return ApiError(ERR_EQUIPMENT_BUSY, 409, msg)


def remote_stand_full(msg="Remote stand capacity would be exceeded."):
    return ApiError(ERR_REMOTE_STAND_FULL, 409, msg)


def slot_double_booked(msg="Slot already confirmed/used for this movement and minute."):
    return ApiError(ERR_SLOT_DOUBLE_BOOKED, 409, msg)


def turn_time_too_short(msg="Occupancy window shorter than the minimum turn time."):
    return ApiError(ERR_TURN_TIME_TOO_SHORT, 422, msg)


def slot_window_missed(msg="Clock outside the slot tolerance window."):
    return ApiError(ERR_SLOT_WINDOW_MISSED, 422, msg)


def stale_gate_version(msg="expected_gate_version does not match the gate's current version."):
    return ApiError(ERR_STALE_GATE_VERSION, 412, msg)


def validation_error(msg="Pagination or semantic validation failed."):
    return ApiError(ERR_VALIDATION, 422, msg)
