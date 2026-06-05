"""Error classes and error-id constants.

Every error_id and its HTTP status is taken verbatim from the PRD §5
Error Code Catalogue / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    """Carries the scaffold-defined error_id, message, and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id -> http_status (PRD §5)
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_OWNER_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_ROLL_NOT_OPEN": 409,
    "ERR_PRIOR_ROLL_NOT_CERTIFIED": 409,
    "ERR_NO_CERTIFIED_SUCCESSOR": 409,
    "ERR_EXEMPTIONS_PENDING": 409,
    "ERR_OPEN_APPEAL_EXISTS": 409,
    "ERR_NO_HELD_HEARING": 409,
    "ERR_ASSESSMENTS_NOT_FINAL": 409,
    "ERR_DUPLICATE_EXEMPTION": 409,
    "ERR_PANEL_SLOT_CONFLICT": 409,
    "ERR_MAX_ROUNDS_REACHED": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_SALE_REASSESSMENT_REQUIRED": 422,
    "ERR_EXEMPTION_INELIGIBLE": 422,
    "ERR_SETTLEMENT_OUT_OF_RANGE": 422,
    "ERR_PAYMENT_EXCEEDS_BALANCE": 422,
    "ERR_INVALID_REQUEST": 400,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
