"""Error classes and error ID constants."""


class APIError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Auth
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"

# Existence / structural
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"

# State / OCC
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_STALE_PROGRAM_VERSION = "ERR_STALE_PROGRAM_VERSION"
ERR_STALE_ENTRY_VERSION = "ERR_STALE_ENTRY_VERSION"
ERR_STALE_INCIDENT_VERSION = "ERR_STALE_INCIDENT_VERSION"

# Business
ERR_DEAD_PERIOD_CONTACT = "ERR_DEAD_PERIOD_CONTACT"
ERR_QUIET_PERIOD_VIOLATION = "ERR_QUIET_PERIOD_VIOLATION"
ERR_OUTSIDE_RECRUITING_WINDOW = "ERR_OUTSIDE_RECRUITING_WINDOW"
ERR_PERIOD_OVERLAP = "ERR_PERIOD_OVERLAP"
ERR_PORTAL_WINDOW_CLOSED = "ERR_PORTAL_WINDOW_CLOSED"
ERR_COACH_PROGRAM_MISMATCH = "ERR_COACH_PROGRAM_MISMATCH"
ERR_SOD_VIOLATION = "ERR_SOD_VIOLATION"
ERR_ATHLETE_NOT_CERTIFIED = "ERR_ATHLETE_NOT_CERTIFIED"
ERR_PROGRAM_UNDER_SANCTION = "ERR_PROGRAM_UNDER_SANCTION"
ERR_SLOT_CAP_EXCEEDED = "ERR_SLOT_CAP_EXCEEDED"
ERR_ZERO_VALUE_INCIDENT = "ERR_ZERO_VALUE_INCIDENT"
ERR_INVALID_INTERVAL = "ERR_INVALID_INTERVAL"


# Helper constructors -----------------------------------------------
def unauthenticated(msg: str = "Missing X-User-ID or X-User-Role header.") -> APIError:
    return APIError(ERR_UNAUTHENTICATED, msg, 401)


def unauthorized(msg: str = "Role is not authorized for this endpoint.") -> APIError:
    return APIError(ERR_UNAUTHORIZED, msg, 403)


def not_found(msg: str = "Resource not found.") -> APIError:
    return APIError(ERR_NOT_FOUND, msg, 404)


def invalid_request(msg: str = "Malformed or missing request fields.") -> APIError:
    return APIError(ERR_INVALID_REQUEST, msg, 400)


def invalid_state(msg: str = "Resource is not in a state that permits this transition.") -> APIError:
    return APIError(ERR_INVALID_STATE, msg, 409)
