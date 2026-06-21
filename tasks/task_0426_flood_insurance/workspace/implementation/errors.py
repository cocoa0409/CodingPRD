"""Error classes and error-id constants for the Flood Insurance API."""


class ApiError(Exception):
    """An application error carrying the scaffold's error_id, message, and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalog (PRD §5 / scaffold §1.6) ---
ERR_VALIDATION = "ERR_VALIDATION"                                  # 400
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"                        # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                                    # 403
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"                  # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                                    # 404
ERR_INVALID_STATE = "ERR_INVALID_STATE"                            # 409
ERR_COMMUNITY_NOT_PARTICIPATING = "ERR_COMMUNITY_NOT_PARTICIPATING"  # 409
ERR_RATING_METHOD_NOT_ELIGIBLE = "ERR_RATING_METHOD_NOT_ELIGIBLE"  # 422
ERR_COVERAGE_LIMIT_EXCEEDED = "ERR_COVERAGE_LIMIT_EXCEEDED"        # 422
ERR_WAITING_PERIOD_NOT_ELAPSED = "ERR_WAITING_PERIOD_NOT_ELAPSED"  # 409
ERR_POLICY_NOT_ACTIVE = "ERR_POLICY_NOT_ACTIVE"                    # 409
ERR_LOSS_OUTSIDE_COVERAGE = "ERR_LOSS_OUTSIDE_COVERAGE"            # 409
ERR_PROOF_OF_LOSS_LATE = "ERR_PROOF_OF_LOSS_LATE"                  # 409
ERR_PROOF_OF_LOSS_MISSING = "ERR_PROOF_OF_LOSS_MISSING"           # 409
ERR_PROOF_OF_LOSS_MISMATCH = "ERR_PROOF_OF_LOSS_MISMATCH"          # 422
ERR_ICC_NOT_ELIGIBLE = "ERR_ICC_NOT_ELIGIBLE"                      # 422
ERR_POLICY_NOT_EXPIRED = "ERR_POLICY_NOT_EXPIRED"                  # 409
ERR_STALE_POLICY_VERSION = "ERR_STALE_POLICY_VERSION"             # 412
ERR_STALE_CLAIM_VERSION = "ERR_STALE_CLAIM_VERSION"               # 412


# Convenience constructors that pin the HTTP status from the catalog.
def validation(msg="Invalid request body"):
    return ApiError(ERR_VALIDATION, 400, msg)


def unauthenticated(msg="Missing or unrecognized role"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Role not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_resource_owner(msg="Acting user is not the owner of this resource"):
    return ApiError(ERR_NOT_RESOURCE_OWNER, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_state(msg="Resource is not in the required state for this transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)
