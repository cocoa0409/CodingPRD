"""Error catalogue (PRD section 5 / SCAFFOLD 1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = (message or DEFAULT_MESSAGES.get(error_id)
                        or _humanise(error_id))


def _humanise(error_id):
    """Readable fallback message for an error id raised without one."""
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") \
        else error_id.replace("_", " ").lower()
    return (words[:1].upper() + words[1:] + ".") if words else error_id


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_CARRIER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CARRIER_NOT_FOUND": 404,
    "ERR_DRIVER_NOT_FOUND": 404,
    "ERR_VIOLATION_CODE_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_VIOLATION_NOT_FOUND": 404,
    "ERR_AMENDMENT_NOT_FOUND": 404,
    "ERR_CHALLENGE_NOT_FOUND": 404,
    "ERR_ADJUDICATION_NOT_FOUND": 404,
    "ERR_BASIC_SCORE_NOT_FOUND": 404,
    "ERR_COACHING_NOT_FOUND": 404,
    "ERR_CAP_NOT_FOUND": 404,
    "ERR_CAP_ITEM_NOT_FOUND": 404,
    "ERR_SCORING_RUN_NOT_FOUND": 404,
    "ERR_STALE_CARRIER_VERSION": 412,
    "ERR_STALE_REPORT_VERSION": 412,
    "ERR_STALE_VIOLATION_VERSION": 412,
    "ERR_INVALID_REPORT_STATE": 409,
    "ERR_INVALID_CHALLENGE_STATE": 409,
    "ERR_INVALID_ADJUDICATION_STATE": 409,
    "ERR_ALREADY_APPLIED_TO_RECORD": 409,
    "ERR_ADJUDICATION_SUPERSEDED": 409,
    "ERR_VIOLATION_NOT_ACTIVE": 409,
    "ERR_INVALID_COACHING_STATE": 409,
    "ERR_INVALID_CAP_STATE": 409,
    "ERR_INVALID_CAP_ITEM_STATE": 409,
    "ERR_OOS_REMOVAL_REQUIRES_ADJUDICATION": 422,
    "ERR_DRIVER_NOT_EMPLOYED": 422,
    "ERR_VIOLATION_NOT_ATTRIBUTED_TO_DRIVER": 422,
    "ERR_CODE_NOT_DRIVER_ATTRIBUTABLE": 422,
    "ERR_DRIVER_CARRIER_MISMATCH": 422,
    "ERR_DRIVER_ATTRIBUTION_MISSING": 422,
    "ERR_CHALLENGE_FILING_WINDOW_CLOSED": 422,
    "ERR_INFO_RESPONSE_WINDOW_CLOSED": 422,
    "ERR_SCORING_RUN_SNAPSHOT_REGRESSION": 409,
    "ERR_CHALLENGE_PAYLOAD_INCOMPLETE": 422,
    "ERR_CHALLENGE_TARGET_MISMATCH": 422,
    "ERR_DUPLICATE_TARGET_INVALID": 422,
    "ERR_AMENDMENT_PAYLOAD_INCOMPLETE": 422,
    "ERR_AMENDMENT_TARGET_MISMATCH": 422,
    "ERR_EVIDENCE_REQUIRED": 422,
    "ERR_THRESHOLD_NOT_CONFIGURED": 409,
    "ERR_DUPLICATE_INSPECTION_WINDOW": 409,
    "ERR_COACHING_WINDOW_CONFLICT": 409,
    "ERR_DUPLICATE_DOT_NUMBER": 409,
    "ERR_DUPLICATE_VIOLATION_CODE": 409,
    "ERR_DUPLICATE_REPORT_NUMBER": 409,
    "ERR_DUPLICATE_CDL": 409,
    "ERR_DUPLICATE_OPEN_CHALLENGE": 409,
    "ERR_CHALLENGE_ROUND_LIMIT_EXCEEDED": 409,
    "ERR_ADJUDICATION_PENDING_EXISTS": 409,
    "ERR_ACTIVE_CAP_EXISTS": 409,
    "ERR_CAP_NOT_REQUIRED": 422,
    "ERR_CAP_ITEMS_INCOMPLETE": 422,
    "ERR_REVIEW_BRANCH_ALREADY_RECORDED": 409,
    "ERR_SCREENING_SELECTION_INCONSISTENT": 422,
    "ERR_CHALLENGE_QUOTA_EXCEEDED": 409,
    "ERR_NOT_FOUND": 404,
    "ERR_INTERNAL": 500,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and a recognised X-User-Role are required.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not authorised for this endpoint.",
    "ERR_CARRIER_SCOPE_VIOLATION": "The addressed resource belongs to a different carrier.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this actor from performing this operation.",
    "ERR_INVALID_REQUEST": "The request payload is malformed.",
    "ERR_NOT_FOUND": "The requested resource does not exist.",
    "ERR_INTERNAL": "Internal server error.",
}


def err(error_id, message=None):
    return ApiError(error_id, message)
