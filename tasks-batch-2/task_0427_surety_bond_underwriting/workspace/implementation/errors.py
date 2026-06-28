"""Error classes and error-id constants for the Surety Bond Underwriting API.

Error catalog and HTTP statuses are taken verbatim from PRD §5 / scaffold §1.6.
"""


class ApiError(Exception):
    """An application error carrying the scaffold's error_id, message, and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalog (PRD §5 / scaffold §1.6) ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                        # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"           # 422
ERR_INVALID_STATE = "ERR_INVALID_STATE"               # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"               # 412
ERR_INDEMNITY_REQUIRED = "ERR_INDEMNITY_REQUIRED"     # 409
ERR_REFERRAL_REQUIRED = "ERR_REFERRAL_REQUIRED"       # 409
ERR_SINGLE_LIMIT_EXCEEDED = "ERR_SINGLE_LIMIT_EXCEEDED"        # 409
ERR_AGGREGATE_LIMIT_EXCEEDED = "ERR_AGGREGATE_LIMIT_EXCEEDED"  # 409
ERR_TREATY_CAPACITY_EXCEEDED = "ERR_TREATY_CAPACITY_EXCEEDED"  # 409
ERR_TREATY_CLOSED = "ERR_TREATY_CLOSED"               # 409
ERR_PROGRAM_SUSPENDED = "ERR_PROGRAM_SUSPENDED"       # 409
ERR_OPEN_CLAIM_EXISTS = "ERR_OPEN_CLAIM_EXISTS"       # 409
ERR_LOSS_EXCEEDS_PENAL_SUM = "ERR_LOSS_EXCEEDS_PENAL_SUM"  # 409


# Convenience constructors that pin the HTTP status from the catalog.
def unauthenticated(msg="Missing or unrecognized role"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Role not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Invalid request body"):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def invalid_state(msg="Resource is not in the required state for this transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def stale_version(msg="expected_bond_version does not match the bond's current version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)
