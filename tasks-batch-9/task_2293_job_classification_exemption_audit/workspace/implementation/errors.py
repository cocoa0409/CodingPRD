"""Error catalogue (PRD section 5 / SCAFFOLD 1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


DEFAULT_MESSAGES = {
    "ERR_MISSING_USER_CONTEXT": "X-User-ID and X-User-Role headers are required.",
    "ERR_INVALID_REQUEST": "The request body or query parameters are invalid.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not permitted to call this endpoint.",
    "ERR_SEGREGATION_OF_DUTIES": "The acting operator may not decide their own work.",
    "ERR_AUDIT_PROJECT_NOT_FOUND": "The audit project does not exist.",
    "ERR_JOB_FAMILY_NOT_FOUND": "The job family does not exist.",
    "ERR_POSITION_NOT_FOUND": "The position does not exist.",
    "ERR_INTERVIEW_NOT_FOUND": "The interview does not exist.",
    "ERR_ANALYSIS_NOT_FOUND": "The exemption analysis does not exist.",
    "ERR_RECLASS_CASE_NOT_FOUND": "The reclassification case does not exist.",
    "ERR_CORRECTION_NOT_FOUND": "The voluntary correction does not exist.",
    "ERR_CONTRACTOR_REVIEW_NOT_FOUND": "The contractor review does not exist.",
    "ERR_DUPLICATE_CODE": "The code is already in use within its scope.",
    "ERR_DUPLICATE_INTERVIEW_RESPONDENT": "A live interview already exists for this position and respondent type.",
    "ERR_DUTY_TIME_OVERALLOCATED": "The position's claimed time percentages would exceed 100.",
    "ERR_IC_TEST_INPUTS_MISSING": "The inputs required by the applicable independent-contractor test were not all supplied.",
    "ERR_INVALID_STATE_TRANSITION": "No declared transition exists from the entity's current state for this trigger.",
    "ERR_INTERVIEW_NOT_STARTED": "The interview has not been completed.",
    "ERR_PROJECT_STAGE_INVALID": "The engagement is not in the stage this operation requires.",
    "ERR_PROJECT_STAGE_PRECONDITION_UNMET": "The requested stage transition's preconditions do not hold.",
    "ERR_PROJECT_NOT_READY_TO_CLOSE": "The engagement still has open remediation work.",
    "ERR_PROJECT_POSTURE_FROZEN": "The engagement's remediation posture is FROZEN.",
    "ERR_POSTURE_RESTRICTED_FAMILY": "The engagement is RESTRICTED and the target family's risk tier is HIGH or CRITICAL.",
    "ERR_DUTIES_NOT_CORROBORATED": "The position's duties are not corroborated.",
    "ERR_INTERVIEWER_DOUBLE_BOOKED": "The interviewer's calendar window is already reserved.",
    "ERR_RECLASS_WINDOW_CONFLICT": "The reclassification window is not sufficiently separated from an existing window.",
    "ERR_RECLASS_WAVE_CAPACITY_EXCEEDED": "The job family's reclassification wave capacity is exhausted.",
    "ERR_POSITION_NOT_MISCLASSIFIED": "The position's classification status is not MISCLASSIFIED.",
    "ERR_VOLUNTARY_CORRECTION_REQUIRED": "An APPROVED voluntary correction is required at this exposure level.",
    "ERR_RECLASS_ALREADY_CONVERTED": "A reclassification case for this position is already CONVERTED.",
    "ERR_CASE_ALREADY_COMPLETED": "The case's communication status is ACKNOWLEDGED.",
    "ERR_NOTICE_WINDOW_TOO_SHORT": "The notice lead time is shorter than the jurisdiction's minimum.",
    "ERR_APPROVAL_AUTHORITY_EXCEEDED": "The approved amount exceeds the delegated authority cap.",
    "ERR_CORRECTION_AMOUNT_BELOW_EXPOSURE": "A SELF_CORRECT_FULL correction must be funded to at least the case's exposure.",
    "ERR_STALE_POSITION_VERSION": "expected_position_version does not match the position's current version.",
    "ERR_STALE_CASE_VERSION": "expected_reclassification_case_version does not match the case's current version.",
}

HTTP = {
    "ERR_MISSING_USER_CONTEXT": 400,
    "ERR_INVALID_REQUEST": 400,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_AUDIT_PROJECT_NOT_FOUND": 404,
    "ERR_JOB_FAMILY_NOT_FOUND": 404,
    "ERR_POSITION_NOT_FOUND": 404,
    "ERR_INTERVIEW_NOT_FOUND": 404,
    "ERR_ANALYSIS_NOT_FOUND": 404,
    "ERR_RECLASS_CASE_NOT_FOUND": 404,
    "ERR_CORRECTION_NOT_FOUND": 404,
    "ERR_CONTRACTOR_REVIEW_NOT_FOUND": 404,
    "ERR_DUPLICATE_CODE": 409,
    "ERR_DUPLICATE_INTERVIEW_RESPONDENT": 409,
    "ERR_DUTY_TIME_OVERALLOCATED": 409,
    "ERR_IC_TEST_INPUTS_MISSING": 409,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_INTERVIEW_NOT_STARTED": 409,
    "ERR_PROJECT_STAGE_INVALID": 409,
    "ERR_PROJECT_STAGE_PRECONDITION_UNMET": 409,
    "ERR_PROJECT_NOT_READY_TO_CLOSE": 409,
    "ERR_PROJECT_POSTURE_FROZEN": 409,
    "ERR_POSTURE_RESTRICTED_FAMILY": 409,
    "ERR_DUTIES_NOT_CORROBORATED": 409,
    "ERR_INTERVIEWER_DOUBLE_BOOKED": 409,
    "ERR_RECLASS_WINDOW_CONFLICT": 409,
    "ERR_RECLASS_WAVE_CAPACITY_EXCEEDED": 409,
    "ERR_POSITION_NOT_MISCLASSIFIED": 409,
    "ERR_VOLUNTARY_CORRECTION_REQUIRED": 409,
    "ERR_RECLASS_ALREADY_CONVERTED": 409,
    "ERR_CASE_ALREADY_COMPLETED": 409,
    "ERR_NOTICE_WINDOW_TOO_SHORT": 409,
    "ERR_APPROVAL_AUTHORITY_EXCEEDED": 409,
    "ERR_CORRECTION_AMOUNT_BELOW_EXPOSURE": 409,
    "ERR_STALE_POSITION_VERSION": 412,
    "ERR_STALE_CASE_VERSION": 412,
}


def fail(error_id, message=None):
    """Raise the catalogued error with its catalogued HTTP status."""
    raise ApiError(error_id, HTTP[error_id], message)
