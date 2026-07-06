class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http_status
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_REFERENTIAL_MISMATCH": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_CONTRACT_VERSION": 412,
    "ERR_CONFIDENTIALITY_BLOCKED": 403,
    "ERR_CONTRACT_NOT_ACTIVE": 409,
    "ERR_EMPLOYEE_INELIGIBLE": 409,
    "ERR_ANNUAL_CAP_EXCEEDED": 409,
    "ERR_ALLOTMENT_EXHAUSTED": 409,
    "ERR_WORKLIFE_CAP_EXCEEDED": 409,
    "ERR_CASE_HAS_OPEN_SESSIONS": 409,
    "ERR_SESSION_NOT_COMPLETED": 409,
    "ERR_SESSION_IN_PAST": 422,
    "ERR_PROVIDER_DOUBLE_BOOKED": 409,
    "ERR_CASE_SAME_DAY_SESSION": 409,
    "ERR_NO_PROVIDER_AVAILABLE": 409,
    "ERR_NOT_ASSIGNED_PROVIDER": 403,
    "ERR_DISPOSITION_NOT_ESCALATABLE": 409,
    "ERR_DISPOSITION_NOT_RESOLVABLE": 409,
    "ERR_IMMINENT_REQUIRES_ESCALATION": 409,
    "ERR_INVALID_WINDOW": 422,
    "ERR_PLAN_NOT_PUBLISHED": 409,
    "ERR_DEPENDENT_NOT_UNDER_EMPLOYEE": 409,
    "ERR_DUPLICATE_EXTERNAL_REF": 409,
    "ERR_CLAIM_ALREADY_CLAIMED": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)
