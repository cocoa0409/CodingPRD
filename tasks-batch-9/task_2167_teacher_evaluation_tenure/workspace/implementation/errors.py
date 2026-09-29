"""Error catalogue (SCAFFOLD 1.6 / PRD 5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_EDUCATOR_NOT_FOUND": 404,
    "ERR_EVALUATOR_NOT_FOUND": 404,
    "ERR_CYCLE_NOT_FOUND": 404,
    "ERR_OBSERVATION_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_APPEAL_NOT_FOUND": 404,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_DUPLICATE_EMPLOYEE_NUMBER": 409,
    "ERR_STALE_OBSERVATION_VERSION": 412,
    "ERR_STALE_CYCLE_VERSION": 412,
    "ERR_STALE_PLAN_VERSION": 412,
    "ERR_OBSERVATION_STATE_INVALID": 409,
    "ERR_CYCLE_STATE_INVALID": 409,
    "ERR_PLAN_STATE_INVALID": 409,
    "ERR_APPEAL_STATE_INVALID": 409,
    "ERR_GRIEVANCE_STATE_INVALID": 409,
    "ERR_TENURE_STATE_INVALID": 409,
    "ERR_DISPUTE_IN_PROGRESS": 409,
    "ERR_EVALUATOR_NOT_CERTIFIED": 422,
    "ERR_EVALUATOR_CERTIFICATION_LAPSED": 422,
    "ERR_EVALUATOR_WINDOW_CONFLICT": 409,
    "ERR_FORMAL_SPACING_VIOLATION": 409,
    "ERR_APPEAL_WINDOW_CLOSED": 422,
    "ERR_CLOSE_BEFORE_APPEAL_DEADLINE": 422,
    "ERR_PLAN_PAST_DUE": 422,
    "ERR_CYCLE_OBSERVATIONS_PENDING": 422,
    "ERR_APPEAL_NOT_EXHAUSTED": 422,
    "ERR_PLAN_EXTENSION_LIMIT": 422,
    "ERR_TENURE_NOT_ELIGIBLE": 422,
    "ERR_EVALUATION_BUDGET_EXCEEDED": 402,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or the role is not recognised.",
    "ERR_UNAUTHORIZED": "The acting role is not authorised for this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The acting user does not own this resource.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this action.",
    "ERR_INVALID_REQUEST": "The request is malformed.",
    "ERR_EDUCATOR_NOT_FOUND": "The referenced educator does not exist.",
    "ERR_EVALUATOR_NOT_FOUND": "The referenced evaluator does not exist.",
    "ERR_CYCLE_NOT_FOUND": "The referenced evaluation cycle does not exist.",
    "ERR_OBSERVATION_NOT_FOUND": "The referenced observation does not exist.",
    "ERR_PLAN_NOT_FOUND": "The referenced improvement plan does not exist.",
    "ERR_APPEAL_NOT_FOUND": "The referenced appeal does not exist.",
    "ERR_RESOURCE_NOT_FOUND": "The referenced resource does not exist.",
    "ERR_DUPLICATE_EMPLOYEE_NUMBER": "An educator already exists with that employee number.",
    "ERR_STALE_OBSERVATION_VERSION": "expected_observation_version does not match the observation version.",
    "ERR_STALE_CYCLE_VERSION": "expected_cycle_version does not match the cycle version.",
    "ERR_STALE_PLAN_VERSION": "expected_plan_version does not match the plan version.",
    "ERR_OBSERVATION_STATE_INVALID": "The observation is not in a state that permits this transition.",
    "ERR_CYCLE_STATE_INVALID": "The cycle is not in a state that permits this transition.",
    "ERR_PLAN_STATE_INVALID": "The improvement plan is not in a state that permits this transition.",
    "ERR_APPEAL_STATE_INVALID": "The appeal is not in a state that permits this transition.",
    "ERR_GRIEVANCE_STATE_INVALID": "The grievance is not in a state that permits this transition.",
    "ERR_TENURE_STATE_INVALID": "The educator's tenure status does not permit this action.",
    "ERR_DISPUTE_IN_PROGRESS": "A dispute is in progress on this cycle.",
    "ERR_EVALUATOR_NOT_CERTIFIED": "The evaluator is not certified.",
    "ERR_EVALUATOR_CERTIFICATION_LAPSED": "The evaluator's certification has lapsed.",
    "ERR_EVALUATOR_WINDOW_CONFLICT": "The requested window conflicts with another observation.",
    "ERR_FORMAL_SPACING_VIOLATION": "Formal observation spacing rule violated.",
    "ERR_APPEAL_WINDOW_CLOSED": "The appeal window has closed.",
    "ERR_CLOSE_BEFORE_APPEAL_DEADLINE": "The appeal window has not yet elapsed.",
    "ERR_PLAN_PAST_DUE": "The improvement plan is past due.",
    "ERR_CYCLE_OBSERVATIONS_PENDING": "The cycle still has pending observations.",
    "ERR_APPEAL_NOT_EXHAUSTED": "The internal appeal remedy is not exhausted.",
    "ERR_PLAN_EXTENSION_LIMIT": "The cumulative plan extension cap would be exceeded.",
    "ERR_TENURE_NOT_ELIGIBLE": "The educator is not eligible for a tenure recommendation.",
    "ERR_EVALUATION_BUDGET_EXCEEDED": "The school's evaluation budget would be exceeded.",
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
