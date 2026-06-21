"""Error classes and error catalog (SCAFFOLD.yaml §1.6 / PRD §5)."""


class ApiError(Exception):
    """Carries error_id, message, and http_status for the error envelope."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: id -> http status (PRD §5 / SCAFFOLD §1.6)
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_UNIT_TOO_SMALL": 422,
    "ERR_DUPLICATE_ORDINAL": 422,
    "ERR_PRECOOL_INCOMPLETE": 422,
    "ERR_FSMA_NOT_REGISTERED": 422,
    "ERR_SANITARY_TRAINING_LAPSED": 422,
    "ERR_SANITATION_UNDOCUMENTED": 422,
    "ERR_INVALID_INTERVAL": 422,
    "ERR_CLAIM_NOT_ELIGIBLE": 422,
    "ERR_READING_SHAPE": 422,
    "ERR_STOP_WINDOW_OVERLAP": 409,
    "ERR_READING_OFFSET_DUPLICATE": 409,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE_ASSET_TAG": 422,
    # defensive only — never expected to surface
    "ERR_INTERNAL": 500,
}


def err(error_id, message=None):
    """Build an ApiError for a cataloged error id."""
    return ApiError(error_id, ERRORS[error_id], message)
