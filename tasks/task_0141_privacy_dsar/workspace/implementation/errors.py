"""Error catalogue for the Privacy DSAR API.

Every error_id and its HTTP status comes straight from the PRD §5 / SCAFFOLD §1.6
error catalogue. ApiError carries the machine-readable error_id, the HTTP status,
and a human-readable message which is surfaced in the error response envelope.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status per error_id (PRD §5).
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_DEADLINE_PASSED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_VERIFICATION_ATTEMPTS_EXHAUSTED": 409,
    "ERR_EXEMPTION_BASIS_UNSUPPORTED": 409,
    "ERR_LEGAL_HOLD_ACTIVE": 409,
    "ERR_UNDECIDED_EXEMPTION": 409,
    "ERR_UNRESOLVED_FINDINGS": 409,
    "ERR_NO_FINDINGS": 409,
    "ERR_PROCESSOR_SUSPENDED": 409,
    "ERR_NOTIFICATION_NOT_ACKED": 409,
    "ERR_EXTENSION_LIMIT_REACHED": 409,
    "ERR_FULFILLMENT_INCOMPLETE": 409,
    "ERR_STALE_VERSION": 412,
}


def err(error_id, message=None):
    """Construct an ApiError, deriving HTTP status from the catalogue."""
    return ApiError(error_id, ERROR_STATUS[error_id], message)
