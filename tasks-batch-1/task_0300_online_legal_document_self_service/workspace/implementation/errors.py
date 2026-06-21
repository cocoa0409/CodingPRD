"""Error classes and error-id constants for the Legal Document Self-Service API."""


class ApiError(Exception):
    """Carries an error_id, human message, and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalog (§1.6 / PRD §5) ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"             # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                       # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"           # 400
ERR_REFERENCE_INVALID = "ERR_REFERENCE_INVALID"       # 409
ERR_STALE_PROJECT_VERSION = "ERR_STALE_PROJECT_VERSION"  # 412
ERR_INVALID_STATE = "ERR_INVALID_STATE"               # 409
ERR_SUBSCRIPTION_NOT_ACTIVE = "ERR_SUBSCRIPTION_NOT_ACTIVE"  # 403
ERR_REVIEW_ADDON_NOT_ELECTED = "ERR_REVIEW_ADDON_NOT_ELECTED"  # 409
ERR_QUESTIONNAIRE_INCOMPLETE = "ERR_QUESTIONNAIRE_INCOMPLETE"  # 409
ERR_NO_CLAUSE_TEMPLATES = "ERR_NO_CLAUSE_TEMPLATES"   # 409
ERR_MANDATORY_CLAUSE_MISSING = "ERR_MANDATORY_CLAUSE_MISSING"  # 409
ERR_REVIEW_IN_PROGRESS = "ERR_REVIEW_IN_PROGRESS"     # 409
ERR_ATTORNEY_WINDOW_CONFLICT = "ERR_ATTORNEY_WINDOW_CONFLICT"  # 409
ERR_LEASE_TERM_OVERLAP = "ERR_LEASE_TERM_OVERLAP"     # 409
ERR_REVISION_SUPERSEDED = "ERR_REVISION_SUPERSEDED"   # 409
ERR_PROJECT_NOT_FINALIZED = "ERR_PROJECT_NOT_FINALIZED"  # 409
ERR_NOT_REVIEW_OWNER = "ERR_NOT_REVIEW_OWNER"         # 403
ERR_SIGNER_NOT_INVITED = "ERR_SIGNER_NOT_INVITED"     # 409
ERR_ALREADY_SIGNED = "ERR_ALREADY_SIGNED"             # 409
ERR_NOTARY_NOT_REQUIRED = "ERR_NOTARY_NOT_REQUIRED"   # 409
ERR_NO_CREDITS_REMAINING = "ERR_NO_CREDITS_REMAINING"  # 402
ERR_REMINDER_NOT_DUE = "ERR_REMINDER_NOT_DUE"         # 409


def unauthenticated(msg="Missing or invalid X-User-Role header"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Acting role not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_found(msg="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Missing or invalid request field"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def reference_invalid(msg="Body references are inconsistent"):
    return ApiError(ERR_REFERENCE_INVALID, 409, msg)


def invalid_state(msg="Resource not in a valid state for this transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)
