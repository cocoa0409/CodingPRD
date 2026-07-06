class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http_status
ERR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_CASE_VERSION": 412,
    "ERR_RESIDUAL_BED_TOO_THIN": 422,
    "ERR_ECTASIA_RISK_K": 422,
    "ERR_ERROR_UNTREATABLE": 422,
    "ERR_PATIENT_UNDERAGE": 422,
    "ERR_SCREENING_NOT_APPROVED": 422,
    "ERR_CONSENT_PATIENT_MISMATCH": 422,
    "ERR_CASE_NOT_FUNDED": 422,
    "ERR_DROPS_NOT_STARTED": 422,
    "ERR_SUITE_TIME_CONFLICT": 409,
    "ERR_SURGEON_TIME_CONFLICT": 409,
    "ERR_INVALID_SLOT": 422,
    "ERR_ENHANCEMENT_WINDOW_EXPIRED": 422,
    "ERR_HEAL_TOO_EARLY": 422,
    "ERR_SUITE_DAILY_CAP": 409,
    "ERR_SURGEON_DAILY_CAP": 409,
    "ERR_RESOURCE_UNAVAILABLE": 409,
    "ERR_DEPOSIT_TOO_LOW": 422,
    "ERR_GUARANTEE_NOT_MET": 422,
    "ERR_ENHANCEMENT_ALREADY_FULFILLED": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERR[error_id], message)
