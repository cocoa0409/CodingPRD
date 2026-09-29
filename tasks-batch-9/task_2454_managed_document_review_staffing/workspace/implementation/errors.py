"""Error catalogue (PRD section 5) and the exception type used everywhere."""

ERROR_HTTP_STATUS = {
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_UNKNOWN_ROLE": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_MATTER_CLIENT": 403,
    "ERR_CLIENT_NOT_FOUND": 404,
    "ERR_MATTER_NOT_FOUND": 404,
    "ERR_PROTOCOL_NOT_FOUND": 404,
    "ERR_REVIEWER_NOT_FOUND": 404,
    "ERR_SCREENING_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_BATCH_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_QC_SAMPLE_NOT_FOUND": 404,
    "ERR_PRIVILEGE_ENTRY_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_TIME_WINDOW": 422,
    "ERR_STALE_MATTER_VERSION": 412,
    "ERR_STALE_BATCH_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_MATTER_SUSPENDED": 409,
    "ERR_REVIEWER_REMOVED": 409,
    "ERR_PROTOCOL_NOT_APPROVED": 409,
    "ERR_MIN_STAFFING_UNMET": 409,
    "ERR_CONFLICTS_NOT_CLEARED": 409,
    "ERR_CONFIDENTIALITY_NOT_EXECUTED": 409,
    "ERR_CREDENTIAL_NOT_VERIFIED": 409,
    "ERR_SECOND_LEVEL_SAME_REVIEWER": 409,
    "ERR_QC_VALIDATOR_CONFLICT": 409,
    "ERR_REMOTE_WORK_NOT_AUTHORIZED": 403,
    "ERR_NO_ACTIVE_SESSION": 409,
    "ERR_PRIVILEGE_LOG_INCOMPLETE": 409,
    "ERR_ASSIGNMENT_INCOMPLETE": 409,
    "ERR_SCREENING_ALREADY_OPEN": 409,
    "ERR_CA_COVERAGE_OVERLAP": 409,
    "ERR_MATTER_DEADLINE_PASSED": 409,
    "ERR_SESSION_OUTSIDE_COVERAGE": 422,
    "ERR_SESSION_WINDOW_OVERLAP": 409,
    "ERR_ONSITE_SEATS_EXHAUSTED": 409,
    "ERR_BAR_ADMISSION_MISSING": 422,
    "ERR_REVIEWER_CAPACITY_EXCEEDED": 409,
    "ERR_LANGUAGE_REQUIREMENT_UNMET": 422,
    "ERR_TIER_MISMATCH": 422,
    "ERR_NO_ELIGIBLE_REVIEWER": 409,
    "ERR_ZERO_DOCUMENT_BATCH": 422,
    "ERR_INSUFFICIENT_UNBATCHED_DOCUMENTS": 422,
    "ERR_DOCUMENT_COUNT_EXCEEDED": 422,
    "ERR_ERROR_COUNT_EXCEEDS_SAMPLE": 422,
    "ERR_BATCH_NOT_DISSOLVABLE": 409,
    "ERR_MATTER_NOT_CLOSEABLE": 409,
    "ERR_BUDGET_WOULD_EXCEED": 402,
    # Non-catalogue fallbacks for unroutable requests.
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    text = error_id
    if text.startswith("ERR_"):
        text = text[4:]
    return text.replace("_", " ").capitalize() + "."


def invalid(message="The request payload is invalid."):
    return ApiError("ERR_INVALID_REQUEST", message)
