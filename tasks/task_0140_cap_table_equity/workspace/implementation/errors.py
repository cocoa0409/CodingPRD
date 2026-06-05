"""Domain error class and error-ID constants. PRD §5 / SCAFFOLD §1.6."""
from __future__ import annotations


class APIError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error IDs -- exact strings from PRD §5 / SCAFFOLD §1.6.
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_TABLE_NOT_OPEN = "ERR_TABLE_NOT_OPEN"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_VALIDATION = "ERR_VALIDATION"
ERR_409A_NONCOMPLIANT = "ERR_409A_NONCOMPLIANT"
ERR_VALUATION_EXPIRED = "ERR_VALUATION_EXPIRED"
ERR_WRONG_CLASS_TYPE = "ERR_WRONG_CLASS_TYPE"
ERR_SENIORITY_CYCLE = "ERR_SENIORITY_CYCLE"
ERR_83B_WINDOW_MISSED = "ERR_83B_WINDOW_MISSED"
ERR_EXCEEDS_EXERCISABLE = "ERR_EXCEEDS_EXERCISABLE"
ERR_POOL_INSUFFICIENT = "ERR_POOL_INSUFFICIENT"
ERR_AUTHORIZED_EXCEEDED = "ERR_AUTHORIZED_EXCEEDED"
ERR_GRANT_HAS_EXERCISES = "ERR_GRANT_HAS_EXERCISES"
ERR_ELECTION_BLOCKS_REVERSE = "ERR_ELECTION_BLOCKS_REVERSE"
ERR_VALUATION_WINDOW_OVERLAP = "ERR_VALUATION_WINDOW_OVERLAP"
ERR_BLACKOUT_OVERLAP = "ERR_BLACKOUT_OVERLAP"


def err(error_id: str, message: str, http_status: int) -> APIError:
    return APIError(error_id, message, http_status)


# Convenience constructors -------------------------------------------------

def unauth(msg: str = "Missing or invalid auth headers.") -> APIError:
    return APIError(ERR_UNAUTHENTICATED, msg, 401)


def forbidden(msg: str = "Role not permitted for this operation.") -> APIError:
    return APIError(ERR_FORBIDDEN, msg, 403)


def not_found(resource: str = "Resource") -> APIError:
    return APIError(ERR_NOT_FOUND, f"{resource} not found.", 404)


def invalid_state(msg: str = "Resource is not in a state that permits this transition.") -> APIError:
    return APIError(ERR_INVALID_STATE, msg, 409)


def validation(msg: str) -> APIError:
    return APIError(ERR_VALIDATION, msg, 400)


def stale_version(msg: str = "expected version does not match current version.") -> APIError:
    return APIError(ERR_STALE_VERSION, msg, 412)
