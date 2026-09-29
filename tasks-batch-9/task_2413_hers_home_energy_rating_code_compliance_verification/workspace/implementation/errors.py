"""Error catalogue (PRD §5) and the ApiError exception."""

ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INVALID_REQUEST": 422,
    "ERR_BUILDER_NOT_FOUND": 404,
    "ERR_SUBDIVISION_NOT_FOUND": 404,
    "ERR_PLAN_MODEL_NOT_FOUND": 404,
    "ERR_HOME_NOT_FOUND": 404,
    "ERR_RATER_NOT_FOUND": 404,
    "ERR_RATING_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    "ERR_SAMPLE_SET_NOT_FOUND": 404,
    "ERR_QA_REVIEW_NOT_FOUND": 404,
    "ERR_CORRECTIVE_ACTION_NOT_FOUND": 404,
    "ERR_DOCUMENT_PACKAGE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_RATING_VOID": 409,
    "ERR_RATING_FILE_LOCKED": 409,
    "ERR_STALE_RATING_VERSION": 412,
    "ERR_STALE_SAMPLE_SET_VERSION": 412,
    "ERR_CERTIFICATION_INVALID": 422,
    "ERR_CERT_LEVEL_INSUFFICIENT": 422,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_MISSING_GOVERNING_TEST": 409,
    "ERR_REPRESENTED_HOME_NOT_TESTABLE": 422,
    "ERR_PLAN_MODEL_MISMATCH": 422,
    "ERR_HOME_SUBDIVISION_MISMATCH": 422,
    "ERR_DUPLICATE_LOT_NUMBER": 409,
    "ERR_DUPLICATE_PLAN_CODE": 409,
    "ERR_DUPLICATE_ACTIVE_RATING": 409,
    "ERR_SAMPLING_NOT_ENABLED": 422,
    "ERR_HOME_ALREADY_SAMPLED": 409,
    "ERR_HOME_PERMIT_OUTSIDE_WINDOW": 422,
    "ERR_SAMPLE_SET_SIZE_INVALID": 422,
    "ERR_BUILDER_SAMPLING_INELIGIBLE": 422,
    "ERR_NO_ELIGIBLE_SAMPLE_HOME": 422,
    "ERR_SAMPLE_SET_NO_TESTED_RATING": 409,
    "ERR_RATING_NOT_COMPLIANT": 422,
    "ERR_OPEN_CORRECTIVE_ACTION": 409,
    "ERR_RATER_QA_DEFICIT": 422,
    "ERR_PACKAGE_NOT_ELIGIBLE": 422,
    "ERR_INSPECTOR_WINDOW_CONFLICT": 409,
    "ERR_SAMPLE_WINDOW_CONFLICT": 409,
    "ERR_PROGRAM_BUDGET_EXCEEDED": 422,
    # Fallback for unrouted paths / methods.
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or invalid.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorized for this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The acting user does not own the target resource.",
    "ERR_INVALID_REQUEST": "The request payload failed shape validation.",
}


def message_for(error_id):
    return DEFAULT_MESSAGES.get(
        error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
    )


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_CATALOG.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )
