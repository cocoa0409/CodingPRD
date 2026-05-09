"""Error classes and error ID constants."""


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


# Error id constants
ERR_AUTH_REQUIRED = "ERR_AUTH_REQUIRED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_VERSION_MISMATCH = "ERR_VERSION_MISMATCH"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_POSTURE_BLOCKED = "ERR_POSTURE_BLOCKED"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_REFERENCE_MISMATCH = "ERR_REFERENCE_MISMATCH"
ERR_INVALID_INTERVAL = "ERR_INVALID_INTERVAL"
ERR_PERMIT_REQUIRED = "ERR_PERMIT_REQUIRED"
ERR_LOCATION_OVER_CAPACITY = "ERR_LOCATION_OVER_CAPACITY"
ERR_WEATHER_BLOCKED = "ERR_WEATHER_BLOCKED"
ERR_AUDITION_NOT_PASSED = "ERR_AUDITION_NOT_PASSED"
ERR_ACTOR_CALLSHEET_CONFLICT = "ERR_ACTOR_CALLSHEET_CONFLICT"
ERR_CROSS_PROJECT_CONFLICT = "ERR_CROSS_PROJECT_CONFLICT"
ERR_EQUIPMENT_UNAVAILABLE = "ERR_EQUIPMENT_UNAVAILABLE"
ERR_INVALID_EVENT_PAYLOAD = "ERR_INVALID_EVENT_PAYLOAD"
ERR_BUDGET_OVERALLOCATED = "ERR_BUDGET_OVERALLOCATED"
ERR_RESERVE_INSUFFICIENT = "ERR_RESERVE_INSUFFICIENT"
ERR_OPEN_OBLIGATIONS = "ERR_OPEN_OBLIGATIONS"
ERR_INVALID_PAGINATION = "ERR_INVALID_PAGINATION"
ERR_VALIDATION = "ERR_VALIDATION"


# Convenience raisers
def auth_required(msg=""):
    raise APIError(ERR_AUTH_REQUIRED, 401, msg or "Authentication required")


def forbidden(msg=""):
    raise APIError(ERR_FORBIDDEN, 403, msg or "Forbidden")


def not_found(msg=""):
    raise APIError(ERR_NOT_FOUND, 404, msg or "Not found")


def version_mismatch(msg=""):
    raise APIError(ERR_VERSION_MISMATCH, 409, msg or "Version mismatch")


def invalid_state(msg=""):
    raise APIError(ERR_INVALID_STATE, 409, msg or "Invalid state")


def posture_blocked(msg=""):
    raise APIError(ERR_POSTURE_BLOCKED, 409, msg or "Production posture blocks this operation")


def segregation_of_duties(msg=""):
    raise APIError(ERR_SEGREGATION_OF_DUTIES, 403, msg or "Segregation of duties violation")


def reference_mismatch(msg=""):
    raise APIError(ERR_REFERENCE_MISMATCH, 422, msg or "Foreign key reference mismatch")


def invalid_interval(msg=""):
    raise APIError(ERR_INVALID_INTERVAL, 422, msg or "Invalid interval")


def permit_required(msg=""):
    raise APIError(ERR_PERMIT_REQUIRED, 409, msg or "Permit required")


def location_over_capacity(msg=""):
    raise APIError(ERR_LOCATION_OVER_CAPACITY, 409, msg or "Location capacity exceeded")


def weather_blocked(msg=""):
    raise APIError(ERR_WEATHER_BLOCKED, 409, msg or "Weather blocked")


def audition_not_passed(msg=""):
    raise APIError(ERR_AUDITION_NOT_PASSED, 422, msg or "Actor has no passing audition for this role")


def actor_callsheet_conflict(msg=""):
    raise APIError(ERR_ACTOR_CALLSHEET_CONFLICT, 409, msg or "Actor call sheet conflict")


def cross_project_conflict(msg=""):
    raise APIError(ERR_CROSS_PROJECT_CONFLICT, 409, msg or "Cross-production conflict")


def equipment_unavailable(msg=""):
    raise APIError(ERR_EQUIPMENT_UNAVAILABLE, 409, msg or "Equipment not available")


def invalid_event_payload(msg=""):
    raise APIError(ERR_INVALID_EVENT_PAYLOAD, 422, msg or "Invalid event payload")


def budget_overallocated(msg=""):
    raise APIError(ERR_BUDGET_OVERALLOCATED, 422, msg or "Budget overallocated")


def reserve_insufficient(msg=""):
    raise APIError(ERR_RESERVE_INSUFFICIENT, 409, msg or "Reserve fund insufficient")


def open_obligations(msg=""):
    raise APIError(ERR_OPEN_OBLIGATIONS, 409, msg or "Open obligations remain")


def invalid_pagination(msg=""):
    raise APIError(ERR_INVALID_PAGINATION, 422, msg or "Invalid pagination parameters")


def validation_err(msg=""):
    raise APIError(ERR_VALIDATION, 422, msg or "Request body validation failed")
