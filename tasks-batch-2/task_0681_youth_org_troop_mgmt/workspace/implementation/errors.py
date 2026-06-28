"""Error catalog and the ApiError exception.

Every error_id and HTTP status traces to PRD §5 (Error Code Catalogue) and
SCAFFOLD §1.6.
"""


class ApiError(Exception):
    """Carries an error_id, human-readable message, and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error IDs + HTTP statuses (PRD §5).
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REFERENCE = ("ERR_INVALID_REFERENCE", 422)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_SEGREGATION_OF_DUTIES = ("ERR_SEGREGATION_OF_DUTIES", 409)
ERR_MEMBER_NOT_REGISTERED = ("ERR_MEMBER_NOT_REGISTERED", 409)
ERR_REQUIREMENTS_INCOMPLETE = ("ERR_REQUIREMENTS_INCOMPLETE", 409)
ERR_FORMS_INCOMPLETE = ("ERR_FORMS_INCOMPLETE", 409)
ERR_BOOTH_CONFLICT = ("ERR_BOOTH_CONFLICT", 409)
ERR_MEMBER_DOUBLE_BOOKED = ("ERR_MEMBER_DOUBLE_BOOKED", 409)
ERR_EVENT_FULL = ("ERR_EVENT_FULL", 409)
ERR_INSUFFICIENT_INVENTORY = ("ERR_INSUFFICIENT_INVENTORY", 409)
ERR_INSUFFICIENT_TROOP_FUNDS = ("ERR_INSUFFICIENT_TROOP_FUNDS", 409)
ERR_RECHARTER_NOT_READY = ("ERR_RECHARTER_NOT_READY", 409)
ERR_OVERPAYMENT = ("ERR_OVERPAYMENT", 409)
ERR_DUPLICATE_UNIT_NUMBER = ("ERR_DUPLICATE_UNIT_NUMBER", 409)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)


def err(spec, message=None):
    """Build an ApiError from one of the (error_id, http_status) tuples above."""
    error_id, http_status = spec
    return ApiError(error_id, http_status, message)
