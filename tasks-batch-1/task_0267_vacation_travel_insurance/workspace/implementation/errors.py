"""Error classes and error-id constants for the Vacation Travel Insurance API."""


class ApiError(Exception):
    """Carries an error_id, human-readable message, and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# auth / existence / request
ERR_MISSING_AUTH = "ERR_MISSING_AUTH"            # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                  # 403
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"  # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                  # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"      # 422
ERR_DUPLICATE_CODE = "ERR_DUPLICATE_CODE"        # 409
ERR_DUPLICATE_EMAIL = "ERR_DUPLICATE_EMAIL"      # 409
ERR_DUPLICATE_NAME = "ERR_DUPLICATE_NAME"        # 409

# state / concurrency
ERR_INVALID_STATE = "ERR_INVALID_STATE"          # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"          # 412

# policy lifecycle
ERR_PREMIUM_NOT_PAID = "ERR_PREMIUM_NOT_PAID"    # 409
ERR_NO_INSURED_TRAVELER = "ERR_NO_INSURED_TRAVELER"  # 409
ERR_TRIP_COST_MISMATCH = "ERR_TRIP_COST_MISMATCH"    # 409
ERR_FREE_LOOK_EXPIRED = "ERR_FREE_LOOK_EXPIRED"  # 409
ERR_COVERAGE_PERIOD_STARTED = "ERR_COVERAGE_PERIOD_STARTED"  # 409
ERR_POLICY_HAS_CLAIMS = "ERR_POLICY_HAS_CLAIMS"  # 409
ERR_COVERAGE_OVERLAP = "ERR_COVERAGE_OVERLAP"    # 409

# claim gates
ERR_POLICY_NOT_ACTIVE = "ERR_POLICY_NOT_ACTIVE"  # 409
ERR_FILING_WINDOW_CLOSED = "ERR_FILING_WINDOW_CLOSED"  # 409
ERR_PREEXISTING_NOT_WAIVED = "ERR_PREEXISTING_NOT_WAIVED"  # 409
ERR_NAMED_STORM_CUTOFF = "ERR_NAMED_STORM_CUTOFF"  # 409
ERR_DELAY_BELOW_THRESHOLD = "ERR_DELAY_BELOW_THRESHOLD"  # 409
ERR_DELAY_EVENT_OVERLAP = "ERR_DELAY_EVENT_OVERLAP"  # 409
ERR_DOCUMENTATION_MISSING = "ERR_DOCUMENTATION_MISSING"  # 409
ERR_CLAIM_NOT_APPROVED = "ERR_CLAIM_NOT_APPROVED"  # 409
ERR_AGGREGATE_LIMIT_EXCEEDED = "ERR_AGGREGATE_LIMIT_EXCEEDED"  # 409


def missing_auth(msg="Missing or malformed authentication headers."):
    return ApiError(ERR_MISSING_AUTH, 401, msg)


def forbidden(msg="Role not permitted for this operation."):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_resource_owner(msg="Acting Traveler does not own this resource."):
    return ApiError(ERR_NOT_RESOURCE_OWNER, 403, msg)


def not_found(msg="Resource not found."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Request body is malformed."):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def invalid_state(msg="Resource is not in a state permitting this transition."):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def conflict(error_id, msg=None):
    return ApiError(error_id, 409, msg)
