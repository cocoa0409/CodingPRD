"""Error classes and error ID constants per scaffold §1.6."""


class APIError(Exception):
    """Carries error_id, message, http_status for the standard error envelope."""

    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error ID constants (mirror scaffold §1.6 error catalog)
ERR_VALIDATION_FAILED = "ERR_VALIDATION_FAILED"
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_TEMPLATE_PERMISSION_DENIED = "ERR_TEMPLATE_PERMISSION_DENIED"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_TEMPLATE_NOT_PUBLISHED = "ERR_TEMPLATE_NOT_PUBLISHED"
ERR_PARTY_NOT_ACTIVE = "ERR_PARTY_NOT_ACTIVE"
ERR_CONTRACT_EXPIRED = "ERR_CONTRACT_EXPIRED"
ERR_DUPLICATE_REMINDER = "ERR_DUPLICATE_REMINDER"
ERR_WORKFLOW_LOCKED = "ERR_WORKFLOW_LOCKED"
ERR_REINITIATE_INVALID = "ERR_REINITIATE_INVALID"
ERR_AUTH_FACTORS_INSUFFICIENT = "ERR_AUTH_FACTORS_INSUFFICIENT"
ERR_DELEGATION_INVALID = "ERR_DELEGATION_INVALID"
ERR_TIMESTAMP_HASH_MISMATCH = "ERR_TIMESTAMP_HASH_MISMATCH"
ERR_TIMESTAMP_DRIFT_EXCEEDED = "ERR_TIMESTAMP_DRIFT_EXCEEDED"
ERR_LEGAL_REP_REQUIRES_MFA = "ERR_LEGAL_REP_REQUIRES_MFA"
ERR_NOTARY_REFERENCE_REQUIRED = "ERR_NOTARY_REFERENCE_REQUIRED"


def unauthenticated(msg: str = "Missing or malformed X-User-ID / X-User-Role headers"):
    return APIError(ERR_UNAUTHENTICATED, msg, 401)


def forbidden(msg: str = "Role not authorized for this endpoint"):
    return APIError(ERR_FORBIDDEN, msg, 403)


def not_found(msg: str = "Resource not found"):
    return APIError(ERR_NOT_FOUND, msg, 404)


def invalid_state(msg: str = "Operation not legal in current state"):
    return APIError(ERR_INVALID_STATE, msg, 409)


def version_conflict(msg: str = "OCC version mismatch"):
    return APIError(ERR_VERSION_CONFLICT, msg, 409)


def validation_failed(msg: str = "Request body schema or required-field violation"):
    return APIError(ERR_VALIDATION_FAILED, msg, 400)
