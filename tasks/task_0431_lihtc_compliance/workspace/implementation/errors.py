"""Error classes and error-ID constants for the LIHTC Compliance API."""


class ApiError(Exception):
    """An error that maps to a JSON error envelope with a specific HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (§1.6 / PRD §5)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                  # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_VALIDATION = "ERR_VALIDATION"                      # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"               # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"               # 412
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"  # 403
ERR_STUDENT_INELIGIBLE = "ERR_STUDENT_INELIGIBLE"     # 422
ERR_INCOME_OVER_LIMIT = "ERR_INCOME_OVER_LIMIT"       # 422
ERR_RENT_OVER_LIMIT = "ERR_RENT_OVER_LIMIT"           # 422
ERR_LEASE_OVERLAP = "ERR_LEASE_OVERLAP"               # 409
ERR_INSPECTION_WINDOW_CONFLICT = "ERR_INSPECTION_WINDOW_CONFLICT"  # 409
ERR_AVAILABLE_UNIT_RULE = "ERR_AVAILABLE_UNIT_RULE"   # 409
ERR_SET_ASIDE_NOT_MET = "ERR_SET_ASIDE_NOT_MET"       # 409
ERR_OPEN_FINDINGS_BLOCK_CLOSE = "ERR_OPEN_FINDINGS_BLOCK_CLOSE"  # 409
ERR_RECAPTURE_REQUIRES_NONCOMPLIANT = "ERR_RECAPTURE_REQUIRES_NONCOMPLIANT"  # 409


def unauthenticated(msg="Missing or malformed authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized(msg="Acting role not permitted for this operation"):
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def not_found(msg="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def validation(msg="Malformed body, missing required field, or invalid value"):
    return ApiError(ERR_VALIDATION, 400, msg)


def invalid_state(msg="Resource not in a state permitting the requested transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def stale_version(msg="expected_building_version does not match the building version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)
