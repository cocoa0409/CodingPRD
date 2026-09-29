"""Error catalogue for the Federal Environmental Review API (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# error_id -> HTTP status, transcribed from PRD section 5 / SCAFFOLD errors[]
CATALOGUE = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_AGENCY_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_ACTION_VERSION": 412,
    "ERR_STALE_DECISION_VERSION": 412,
    "ERR_REQUIRED_CONSULTATION_INCOMPLETE": 409,
    "ERR_REFERENCE_MISMATCH": 409,
    "ERR_CONSTRAINT_VIOLATION": 409,
    "ERR_TEMPORAL_CONFLICT": 409,
    "ERR_AGENCY_CAPACITY_EXCEEDED": 409,
    "ERR_AGENCY_SUSPENDED": 409,
    "ERR_ALTERNATIVE_NOT_FEASIBLE": 409,
    "ERR_ALTERNATIVE_STALE": 409,
    "ERR_NO_ADOPTED_PURPOSE_NEED": 409,
    "ERR_SCOPING_PERIOD_TOO_SHORT": 409,
    "ERR_SCOPING_PERIOD_OVERLAP": 409,
    "ERR_COMMENT_PERIOD_TOO_SHORT": 409,
    "ERR_COMMENT_PERIOD_NOT_OPEN": 409,
    "ERR_COMMENT_PERIOD_NOT_ENDED": 409,
    "ERR_UNRESOLVED_COMMENTS": 409,
    "ERR_INSUFFICIENT_ALTERNATIVES": 409,
    "ERR_UNADDRESSED_ISSUES": 409,
    "ERR_ANALYSIS_LOCKED": 409,
    "ERR_MITIGATION_BASIS_REQUIRED": 409,
    "ERR_MITIGATED_FONSI_WITHOUT_COMMITMENT": 409,
    "ERR_FINAL_DOCUMENT_REQUIRED": 409,
    "ERR_OBLIGATION_CAP_EXCEEDED": 409,
    "ERR_OBJECTION_WINDOW_CLOSED": 409,
    "ERR_OBJECTION_STANDING_MISSING": 409,
    "ERR_RECORD_ALREADY_CERTIFIED": 409,
    "ERR_OBJECTIONS_PENDING": 409,
    "ERR_EC_SCREEN_NOT_TRIGGERED": 409,
    "ERR_DUPLICATE_RESOURCE_ANALYSIS": 409,
}


def fail(error_id, message=""):
    """Raise the catalogued error with its catalogued HTTP status."""
    raise ApiError(error_id, message or error_id, CATALOGUE[error_id])


def invalid(message):
    return ApiError("ERR_INVALID_REQUEST", message, 400)


def not_found(message="resource not found"):
    return ApiError("ERR_NOT_FOUND", message, 404)
