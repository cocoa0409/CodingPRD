"""Domain error classes and the error-id catalog (SCAFFOLD §1.6 / PRD §5)."""
from __future__ import annotations


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id constants — verbatim from the scaffold error catalog (PRD §5).
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"                  # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"                    # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                              # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                  # 422
ERR_INVALID_STATE = "ERR_INVALID_STATE"                      # 409
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"      # 403
ERR_EOI_REQUIRED = "ERR_EOI_REQUIRED"                        # 409
ERR_EMPLOYEE_NOT_ELIGIBLE = "ERR_EMPLOYEE_NOT_ELIGIBLE"      # 409
ERR_LIFE_EVENT_WINDOW_EXPIRED = "ERR_LIFE_EVENT_WINDOW_EXPIRED"  # 409
ERR_WAITING_PERIOD_OVERLAP = "ERR_WAITING_PERIOD_OVERLAP"    # 409
ERR_COVERAGE_OVERLAP = "ERR_COVERAGE_OVERLAP"                # 409
ERR_DEPENDENT_NOT_VERIFIED = "ERR_DEPENDENT_NOT_VERIFIED"    # 409
ERR_STALE_EMPLOYEE_VERSION = "ERR_STALE_EMPLOYEE_VERSION"    # 412
ERR_PLAN_ARCHIVED = "ERR_PLAN_ARCHIVED"                      # 409
ERR_FORM_ALREADY_FILED = "ERR_FORM_ALREADY_FILED"           # 409
ERR_VALIDATION_PAGINATION = "ERR_VALIDATION_PAGINATION"      # 422


def unauthenticated(msg: str = "Authentication required") -> APIError:
    return APIError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden_role(msg: str = "Role not permitted for this operation") -> APIError:
    return APIError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_found(msg: str = "Resource not found") -> APIError:
    return APIError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg: str = "Invalid request") -> APIError:
    return APIError(ERR_INVALID_REQUEST, 422, msg)


def invalid_state(msg: str = "Invalid state for this transition") -> APIError:
    return APIError(ERR_INVALID_STATE, 409, msg)


def segregation(msg: str = "Segregation of duties violation") -> APIError:
    return APIError(ERR_SEGREGATION_OF_DUTIES, 403, msg)


def eoi_required(msg: str = "Coverage above guaranteed issue requires EOI") -> APIError:
    return APIError(ERR_EOI_REQUIRED, 409, msg)


def employee_not_eligible(msg: str = "Owning employee is not eligible") -> APIError:
    return APIError(ERR_EMPLOYEE_NOT_ELIGIBLE, 409, msg)


def life_event_window_expired(msg: str = "Life event window expired") -> APIError:
    return APIError(ERR_LIFE_EVENT_WINDOW_EXPIRED, 409, msg)


def waiting_period_overlap(msg: str = "Waiting period overlaps an existing window") -> APIError:
    return APIError(ERR_WAITING_PERIOD_OVERLAP, 409, msg)


def coverage_overlap(msg: str = "Coverage interval overlaps an existing active enrollment") -> APIError:
    return APIError(ERR_COVERAGE_OVERLAP, 409, msg)


def dependent_not_verified(msg: str = "Dependent is not VERIFIED") -> APIError:
    return APIError(ERR_DEPENDENT_NOT_VERIFIED, 409, msg)


def stale_employee_version(msg: str = "expected_employee_version is stale") -> APIError:
    return APIError(ERR_STALE_EMPLOYEE_VERSION, 412, msg)


def plan_archived(msg: str = "Plan offering is archived") -> APIError:
    return APIError(ERR_PLAN_ARCHIVED, 409, msg)


def form_already_filed(msg: str = "Form 1095-C is already filed") -> APIError:
    return APIError(ERR_FORM_ALREADY_FILED, 409, msg)


def validation_pagination(msg: str = "Invalid pagination parameters") -> APIError:
    return APIError(ERR_VALIDATION_PAGINATION, 422, msg)
