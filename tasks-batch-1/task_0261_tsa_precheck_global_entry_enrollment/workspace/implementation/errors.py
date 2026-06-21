"""Domain error classes and the complete error-id catalog (PRD §5 / scaffold §1.6).

Every error_id below is emitted verbatim with the HTTP status the catalog pins.
"""
from __future__ import annotations


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- error-id constants (verbatim from PRD §5 / scaffold §1.6) ---------------
ERR_MISSING_AUTH_HEADERS = "ERR_MISSING_AUTH_HEADERS"            # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"                        # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                                  # 404
ERR_REFERENCED_ENTITY_NOT_FOUND = "ERR_REFERENCED_ENTITY_NOT_FOUND"  # 404
ERR_APPLICANT_NOT_FOUND = "ERR_APPLICANT_NOT_FOUND"             # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                      # 422
ERR_STALE_VERSION = "ERR_STALE_VERSION"                          # 412
ERR_INVALID_STATE = "ERR_INVALID_STATE"                          # 409
ERR_PERMANENTLY_DISQUALIFIED = "ERR_PERMANENTLY_DISQUALIFIED"    # 403
ERR_ELIGIBILITY_CITIZENSHIP = "ERR_ELIGIBILITY_CITIZENSHIP"      # 422
ERR_RENEWAL_SOURCE_INVALID = "ERR_RENEWAL_SOURCE_INVALID"        # 409
ERR_RENEWAL_TOO_EARLY = "ERR_RENEWAL_TOO_EARLY"                  # 409
ERR_FEE_UNPAID = "ERR_FEE_UNPAID"                                # 402
ERR_BACKGROUND_CHECK_EXISTS = "ERR_BACKGROUND_CHECK_EXISTS"      # 409
ERR_VETTING_NOT_CLEARED = "ERR_VETTING_NOT_CLEARED"             # 409
ERR_VETTING_NOT_ADVERSE = "ERR_VETTING_NOT_ADVERSE"             # 409
ERR_CENTER_SUSPENDED = "ERR_CENTER_SUSPENDED"                    # 409
ERR_SLOT_NOT_AVAILABLE = "ERR_SLOT_NOT_AVAILABLE"               # 409
ERR_SLOT_OVERLAP = "ERR_SLOT_OVERLAP"                            # 409
ERR_DAILY_CAPACITY_EXCEEDED = "ERR_DAILY_CAPACITY_EXCEEDED"      # 409
ERR_NO_APPOINTMENT = "ERR_NO_APPOINTMENT"                        # 409
ERR_BIOMETRICS_NOT_ACCEPTED = "ERR_BIOMETRICS_NOT_ACCEPTED"      # 409
ERR_APPOINTMENT_NOT_ELAPSED = "ERR_APPOINTMENT_NOT_ELAPSED"      # 409
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"          # 403
ERR_APPEAL_LIMIT_REACHED = "ERR_APPEAL_LIMIT_REACHED"           # 409
ERR_KTN_NOT_EXPIRED = "ERR_KTN_NOT_EXPIRED"                      # 409
ERR_KTN_COVERAGE_OVERLAP = "ERR_KTN_COVERAGE_OVERLAP"           # 409
ERR_VALIDATION_OUT_OF_RANGE = "ERR_VALIDATION_OUT_OF_RANGE"      # 422
ERR_CLOCK_INVALID = "ERR_CLOCK_INVALID"                          # 422

# Internal-only fallback (never declared in the catalog; used for 500s).
ERR_INTERNAL = "ERR_INTERNAL"


# --- convenience raisers ------------------------------------------------------
def missing_auth(msg: str = "Missing or malformed auth headers"):
    raise APIError(ERR_MISSING_AUTH_HEADERS, 401, msg)


def forbidden(msg: str = "Role not permitted for this endpoint"):
    raise APIError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_found(what: str = "resource"):
    raise APIError(ERR_NOT_FOUND, 404, f"{what} not found")


def referenced_not_found(what: str = "referenced resource"):
    raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 404, f"{what} does not exist")


def applicant_not_found(msg: str = "Applicant does not exist"):
    raise APIError(ERR_APPLICANT_NOT_FOUND, 404, msg)


def invalid_request(msg: str = "Invalid request body"):
    raise APIError(ERR_INVALID_REQUEST, 422, msg)


def invalid_state(msg: str = "Invalid state for this transition"):
    raise APIError(ERR_INVALID_STATE, 409, msg)


def stale_version(msg: str = "expected_application_version does not match"):
    raise APIError(ERR_STALE_VERSION, 412, msg)


def out_of_range(msg: str = "Pagination parameter out of range"):
    raise APIError(ERR_VALIDATION_OUT_OF_RANGE, 422, msg)
