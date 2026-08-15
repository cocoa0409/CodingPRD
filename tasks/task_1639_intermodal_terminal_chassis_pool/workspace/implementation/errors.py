"""Error catalog (scaffold §1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# Error ID constants — exact strings from the scaffold error catalog.
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_CHASSIS_UNROADABLE = "ERR_CHASSIS_UNROADABLE"
ERR_RAIL_CUTOFF_MISSED = "ERR_RAIL_CUTOFF_MISSED"
ERR_OUTSIDE_APPOINTMENT_WINDOW = "ERR_OUTSIDE_APPOINTMENT_WINDOW"
ERR_CONGESTED_WINDOW_CAP = "ERR_CONGESTED_WINDOW_CAP"
ERR_MEMBERSHIP_NOT_ACTIVE = "ERR_MEMBERSHIP_NOT_ACTIVE"
ERR_TERMINAL_CLOSED = "ERR_TERMINAL_CLOSED"
ERR_NO_YARD_SLOT_AVAILABLE = "ERR_NO_YARD_SLOT_AVAILABLE"
ERR_TRAIN_NOT_ARRIVED = "ERR_TRAIN_NOT_ARRIVED"
ERR_OVERPAY = "ERR_OVERPAY"
ERR_OPEN_DAMAGE_EXISTS = "ERR_OPEN_DAMAGE_EXISTS"
ERR_TRANSACTION_IN_FLIGHT = "ERR_TRANSACTION_IN_FLIGHT"
ERR_NO_CHECKED_IN_APPOINTMENT = "ERR_NO_CHECKED_IN_APPOINTMENT"


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_state(msg="Resource is in a state that does not permit this transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def invalid_request(msg="Payload shape invalid"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)
