"""Error types and the complete error catalog (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Catalog: error_id -> http_status (from SCAFFOLD.yaml errors table / PRD section 5)
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_PROJECT_STATE_FORBIDS": 409,
    "ERR_RIG_NOT_MOBILIZED": 409,
    "ERR_SAMPLE_NOT_IN_LAB": 409,
    "ERR_ANALYSIS_NOT_VERIFIED": 409,
    "ERR_ANALYSIS_DATA_STALE": 409,
    "ERR_REPORT_NOT_ISSUABLE": 409,
    "ERR_CLAIM_STATE_FORBIDS": 409,
    "ERR_ORDER_STATE_FORBIDS": 409,
    "ERR_CLEARANCE_MISSING": 409,
    "ERR_CLEARANCE_EXPIRED": 409,
    "ERR_POSTURE_FROZEN": 409,
    "ERR_PLAN_ALREADY_ACTIVE": 409,
    "ERR_PLAN_NOT_EDITABLE": 409,
    "ERR_RIG_DOUBLE_BOOKED": 409,
    "ERR_STANDING_SUSPENDED": 409,
    "ERR_LAB_CAPACITY_EXCEEDED": 409,
    "ERR_RERUN_LIMIT": 409,
    "ERR_SOD_PE_IS_PREPARER": 409,
    "ERR_DUPLICATE_TICKET": 409,
    "ERR_INVALID_WINDOW": 422,
    "ERR_VISIT_DATE_FUTURE": 422,
    "ERR_SAMPLE_PROJECT_MISMATCH": 422,
    "ERR_VISIT_PROJECT_MISMATCH": 422,
    "ERR_OFFSET_PARENT_NOT_REFUSED": 422,
    "ERR_AUTH_CAP_EXCEEDED": 422,
    "ERR_EXTRA_BORINGS_EXHAUSTED": 422,
    "ERR_CLAIM_AMOUNT_INVALID": 422,
    "ERR_APPEAL_LIMIT": 409,
    "ERR_STALE_PROJECT_VERSION": 412,
    "ERR_STALE_REPORT_VERSION": 412,
}


def err(error_id, message):
    """Build an ApiError with the catalogued HTTP status for error_id."""
    return ApiError(error_id, message, ERRORS[error_id])
