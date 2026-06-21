"""Domain error class and error-ID constants."""
from __future__ import annotations


class APIError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error IDs (PRD §5 / SCAFFOLD §1.6)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_SEGREGATION_OF_DUTIES_VIOLATED = "ERR_SEGREGATION_OF_DUTIES_VIOLATED"
ERR_EXECUTOR_BENEFICIARY_CONFLICT = "ERR_EXECUTOR_BENEFICIARY_CONFLICT"
ERR_CONTINGENT_PARENT_INVALID = "ERR_CONTINGENT_PARENT_INVALID"
ERR_CREDITOR_WINDOW_CLOSED = "ERR_CREDITOR_WINDOW_CLOSED"
ERR_SHARE_OVERALLOCATION = "ERR_SHARE_OVERALLOCATION"
ERR_SHARE_NOT_FULLY_ALLOCATED = "ERR_SHARE_NOT_FULLY_ALLOCATED"
ERR_WARD_OVER_AGE = "ERR_WARD_OVER_AGE"
ERR_INSUFFICIENT_ESTATE_FUNDS = "ERR_INSUFFICIENT_ESTATE_FUNDS"
ERR_DUPLICATE_EXECUTOR_ACTIVE = "ERR_DUPLICATE_EXECUTOR_ACTIVE"
ERR_STALE_ESTATE_VERSION = "ERR_STALE_ESTATE_VERSION"
ERR_HIPAA_RECIPIENTS_REQUIRED = "ERR_HIPAA_RECIPIENTS_REQUIRED"
ERR_POA_INTERVAL_OVERLAP = "ERR_POA_INTERVAL_OVERLAP"
ERR_DUPLICATE_WARD = "ERR_DUPLICATE_WARD"


def err(error_id: str, message: str, http_status: int) -> APIError:
    return APIError(error_id, message, http_status)


# Convenience constructors -------------------------------------------------

def unauth(msg: str = "Missing or invalid auth headers.") -> APIError:
    return APIError(ERR_UNAUTHENTICATED, msg, 401)


def forbidden(msg: str = "Role not permitted for this operation.") -> APIError:
    return APIError(ERR_UNAUTHORIZED, msg, 403)


def not_found(resource: str = "Resource") -> APIError:
    return APIError(ERR_NOT_FOUND, f"{resource} not found.", 404)


def invalid_state(msg: str = "Resource is not in a state that permits this transition.") -> APIError:
    return APIError(ERR_INVALID_STATE, msg, 409)


def invalid_request(msg: str) -> APIError:
    return APIError(ERR_INVALID_REQUEST, msg, 400)


def stale_version(msg: str = "expected_estate_version does not match current Estate.version.") -> APIError:
    return APIError(ERR_STALE_ESTATE_VERSION, msg, 412)
