"""Error catalogue (PRD section 5)."""

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_UNIT_NOT_FOUND": 404,
    "ERR_BED_NOT_FOUND": 404,
    "ERR_SHIFT_NOT_FOUND": 404,
    "ERR_PATIENT_NOT_FOUND": 404,
    "ERR_AUTHORIZATION_NOT_FOUND": 404,
    "ERR_ADMISSION_NOT_FOUND": 404,
    "ERR_TAPER_PLAN_NOT_FOUND": 404,
    "ERR_STUDY_NOT_FOUND": 404,
    "ERR_ALERT_NOT_FOUND": 404,
    "ERR_MARKING_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_EXPORT_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_INVALID_AUTHORIZATION_STATE": 409,
    "ERR_INVALID_ADMISSION_STATE": 409,
    "ERR_INVALID_TAPER_STATE": 409,
    "ERR_INVALID_STUDY_STATE": 409,
    "ERR_INVALID_DATA_STATE": 409,
    "ERR_INVALID_ALERT_STATE": 409,
    "ERR_INVALID_MARKING_STATE": 409,
    "ERR_INVALID_REPORT_STATE": 409,
    "ERR_INVALID_EXPORT_STATE": 409,
    "ERR_INVALID_CASE_STATE": 409,
    "ERR_INVALID_SHIFT_STATE": 409,
    "ERR_STALE_ADMISSION_VERSION": 412,
    "ERR_STALE_STUDY_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_TAPER_BLOCKED_BY_OPEN_EVENT": 409,
    "ERR_INTERVENTION_REQUIRED": 409,
    "ERR_NO_TECH_COVERAGE": 409,
    "ERR_TECH_CAPACITY_EXCEEDED": 409,
    "ERR_SETTING_MISMATCH": 422,
    "ERR_BED_OCCUPANCY_CONFLICT": 409,
    "ERR_BED_REQUIRED_FOR_INPATIENT": 422,
    "ERR_BED_NOT_ALLOWED_FOR_AMBULATORY": 422,
    "ERR_REPORT_NOT_FINAL": 409,
    "ERR_MARKING_NOT_ADJUDICATED": 409,
    "ERR_EXPORT_NOT_DELIVERED": 409,
    "ERR_AUTHORIZATION_NOT_APPROVED": 409,
    "ERR_AUTHORIZATION_DAYS_EXHAUSTED": 402,
    "ERR_UNIT_STORAGE_LOCKED": 409,
    "ERR_STORAGE_QUOTA_EXCEEDED": 409,
    "ERR_RESUBMISSION_LIMIT": 409,
    "ERR_ADDENDUM_LIMIT": 409,
    "ERR_DEFER_LIMIT": 409,
    "ERR_DUPLICATE_VOTE": 409,
    "ERR_QUORUM_NOT_MET": 409,
    "ERR_NO_YIELD_BASIS": 422,
    "ERR_TARGET_ALREADY_MET": 409,
    "ERR_MARKING_OUTSIDE_STUDY_WINDOW": 422,
    "ERR_OPEN_STUDY_ON_DISCHARGE": 409,
    "ERR_SHIFT_HAS_ACTIVE_STUDIES": 409,
    "ERR_SHIFT_WINDOW_INVALID": 422,
    "ERR_CLOCK_MONOTONIC": 422,
    "ERR_EXPORT_IN_DECIDED_CASE": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or the declared role is unknown.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not permitted to perform this operation.",
    "ERR_INVALID_REQUEST": "The request payload or query string is invalid.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, _humanise(error_id)
        )


def _humanise(error_id):
    text = error_id
    if text.startswith("ERR_"):
        text = text[4:]
    return text.replace("_", " ").capitalize() + "."
