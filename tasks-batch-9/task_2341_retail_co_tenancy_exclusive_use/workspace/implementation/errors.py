"""Error catalogue (SCAFFOLD 1.6 / PRD 5)."""

# error_id -> http_status
CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_TENANT_SCOPE_FORBIDDEN": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CENTER_NOT_FOUND": 404,
    "ERR_TENANT_NOT_FOUND": 404,
    "ERR_LEASE_NOT_FOUND": 404,
    "ERR_CONDITION_NOT_FOUND": 404,
    "ERR_REQUIREMENT_NOT_FOUND": 404,
    "ERR_CLAUSE_NOT_FOUND": 404,
    "ERR_RESTRICTION_NOT_FOUND": 404,
    "ERR_NOTICE_NOT_FOUND": 404,
    "ERR_DISPUTE_NOT_FOUND": 404,
    "ERR_ELECTION_NOT_FOUND": 404,
    "ERR_MEASUREMENT_NOT_FOUND": 404,
    "ERR_CERTIFICATE_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_CENTER_SCOPE_MISMATCH": 409,
    "ERR_STALE_CENTER_VERSION": 412,
    "ERR_STALE_LEASE_VERSION": 412,
    "ERR_CENTER_EXECUTION_FROZEN": 409,
    "ERR_LEASE_STATE_INVALID": 409,
    "ERR_CONDITION_STATE_INVALID": 409,
    "ERR_NOTICE_STATE_INVALID": 409,
    "ERR_DISPUTE_STATE_INVALID": 409,
    "ERR_ELECTION_STATE_INVALID": 409,
    "ERR_MEASUREMENT_STATE_INVALID": 409,
    "ERR_CERTIFICATE_STATE_INVALID": 409,
    "ERR_PLAN_STATE_INVALID": 409,
    "ERR_REMEDY_NOT_ELIGIBLE": 409,
    "ERR_REMEDY_KIND_NOT_PERMITTED": 422,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_EXCLUSIVE_USE_CONFLICT": 422,
    "ERR_DISPUTE_PENDING": 409,
    "ERR_CURE_PERIOD_NOT_EXPIRED": 409,
    "ERR_RADIUS_WINDOW_OVERLAP": 409,
    "ERR_RADIUS_WINDOW_INACTIVE": 409,
    "ERR_MEASUREMENT_WINDOW_OVERLAP": 409,
    "ERR_ABATEMENT_WINDOW_INVALID": 422,
    "ERR_ABATEMENT_STACK_EXCEEDED": 422,
    "ERR_LENDER_CONDITIONS_NOT_MET": 422,
    "ERR_CERTIFICATE_STALE": 409,
    "ERR_PROTECTED_RIGHTS_CONSENT_REQUIRED": 409,
    "ERR_MEASUREMENT_BASIS_MISMATCH": 422,
    "ERR_CONDITION_KIND_INVALID": 422,
    "ERR_CLAUSE_NOT_ACTIVE": 422,
    "ERR_SUITE_ALREADY_LEASED": 409,
    "ERR_NOT_FOUND": 404,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-Role header absent or not one of the declared roles",
    "ERR_UNAUTHORIZED": "Caller's role is not authorized for this endpoint",
    "ERR_TENANT_SCOPE_FORBIDDEN": "The addressed record belongs to a different tenant",
    "ERR_INVALID_REQUEST": "Request body failed schema validation",
    "ERR_NOT_FOUND": "Resource not found",
}


def default_message(error_id):
    """Human-readable fallback so `message` is never a bare identifier."""
    if error_id in DEFAULT_MESSAGES:
        return DEFAULT_MESSAGES[error_id]
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") \
        else error_id.replace("_", " ").lower()
    return ("Request rejected: %s" % words) if words else error_id


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super(ApiError, self).__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or CATALOG.get(error_id, 400)
        self.message = message or default_message(error_id)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
