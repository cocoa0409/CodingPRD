"""Error catalog (SCAFFOLD.yaml section 1.6 / PRD section 5) and the ApiError exception."""

ERROR_STATUS = {
    # auth / request shape
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_IDENTITY_MISMATCH": 403,
    "ERR_INVALID_REQUEST": 400,
    # family scoped not-found
    "ERR_BRIDGE_NOT_FOUND": 404,
    "ERR_PERSONNEL_NOT_FOUND": 404,
    "ERR_INSPECTION_RECORD_NOT_FOUND": 404,
    "ERR_RATING_RECORD_NOT_FOUND": 404,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_PROGRAM_RECORD_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_BRIDGE_VERSION": 412,
    "ERR_STALE_CYCLE_VERSION": 412,
    # state gating
    "ERR_INSPECTION_STATE_INVALID": 409,
    "ERR_RATING_STATE_INVALID": 409,
    "ERR_FINDING_STATE_INVALID": 409,
    "ERR_PERMIT_STATE_INVALID": 409,
    "ERR_PROGRAM_STATE_INVALID": 409,
    # uniqueness
    "ERR_DUPLICATE_STRUCTURE_NUMBER": 409,
    "ERR_DUPLICATE_PERMIT_NUMBER": 409,
    "ERR_DUPLICATE_ELEMENT_KEY": 409,
    # business safety
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_TEAM_LEADER_NOT_QUALIFIED": 422,
    "ERR_QA_REVIEWER_NOT_QUALIFIED": 422,
    "ERR_RATING_ENGINEER_NOT_LICENSED": 422,
    "ERR_INSPECTION_TYPE_NOT_APPLICABLE": 422,
    "ERR_NO_ELEMENT_CONDITIONS": 422,
    "ERR_ELEMENT_GROUP_MISSING": 422,
    "ERR_ELEMENT_QUANTITY_MISMATCH": 422,
    "ERR_PHOTO_DOCUMENTATION_MISSING": 422,
    "ERR_ELEMENT_INSPECTION_MISMATCH": 422,
    "ERR_NO_CS4_DEFICIENCY": 422,
    "ERR_SEVERITY_INSUFFICIENT_FOR_CLOSURE": 422,
    "ERR_NOTIFICATION_SEQUENCE": 409,
    # temporal
    "ERR_BRIDGE_ACCESS_BUFFER_CONFLICT": 409,
    "ERR_TEAM_LEADER_WINDOW_CONFLICT": 409,
    "ERR_INSPECTION_DATE_OUT_OF_WINDOW": 422,
    # domain rules
    "ERR_RATING_SOURCE_NOT_ACCEPTED": 422,
    "ERR_SCOUR_CRITICAL_POA_MISSING": 422,
    "ERR_PERMIT_DECISION_MISMATCH": 422,
    "ERR_HIGHER_PRIORITY_CANDIDATE_PENDING": 409,
    "ERR_BUDGET_EXCEEDED": 422,
    "ERR_COMPLIANCE_BELOW_THRESHOLD": 422,
    "ERR_BRIDGE_NOT_INSPECTED": 422,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and the role must be a declared role.",
    "ERR_ROLE_NOT_PERMITTED": "The authenticated role is not permitted to perform this operation.",
    "ERR_IDENTITY_MISMATCH": "The person named in the payload must be the acting user.",
    "ERR_INVALID_REQUEST": "The request is malformed.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGE.get(error_id) or _humanize(error_id)
        super().__init__(self.message)


def _humanize(error_id):
    text = error_id[4:] if error_id.startswith("ERR_") else error_id
    return text.replace("_", " ").capitalize() + "."


def api_error(error_id, message=None):
    return ApiError(error_id, message)


def raise_error(error_id, message=None):
    raise ApiError(error_id, message)
