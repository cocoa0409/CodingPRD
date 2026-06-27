"""Error catalogue (PRD §5 / SCAFFOLD Table 6) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error id -> HTTP status, exactly per the PRD §5 catalogue.
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_TECHNICIAN_UNAVAILABLE": 409,
    "ERR_CERTIFICATION_MISMATCH": 409,
    "ERR_NO_CHAMBERS": 409,
    "ERR_EQUIPMENT_NOT_AVAILABLE": 409,
    "ERR_DUPLICATE_ROOM_LABEL": 409,
    "ERR_EQUIPMENT_UNDERSIZED": 409,
    "ERR_CHAMBER_HAS_EQUIPMENT": 409,
    "ERR_DRY_STANDARD_NOT_MET": 409,
    "ERR_EQUIPMENT_STILL_DEPLOYED": 409,
    "ERR_NO_APPROVED_ESTIMATE": 409,
    "ERR_NOTHING_TO_REOPEN": 409,
    "ERR_OVER_COVERAGE_LIMIT": 409,
    "ERR_ESTIMATE_ALREADY_APPROVED": 409,
    "ERR_CLAIM_ALREADY_SETTLED": 409,
    "ERR_STALE_JOB_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)
