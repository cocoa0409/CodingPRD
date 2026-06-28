"""Error catalog (PRD 5 / SCAFFOLD 1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id -> HTTP status (PRD 5 error catalogue / SCAFFOLD 1.6)
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_OFFERING_DEADLINE_PASSED": 409,
    "ERR_BAD_ACTOR_DISQUALIFIED": 422,
    "ERR_ISSUER_NOT_VERIFIED": 409,
    "ERR_ANNUAL_LIMIT_EXCEEDED": 422,
    "ERR_PER_INVESTOR_CAP_EXCEEDED": 422,
    "ERR_OVERSUBSCRIBED": 409,
    "ERR_MINIMUM_NOT_MET": 409,
    "ERR_ISSUER_CAP_EXCEEDED": 422,
    "ERR_INVALID_OFFERING_TERMS": 422,
    "ERR_SECONDARY_NOT_PERMITTED": 422,
    "ERR_CAMPAIGN_WINDOW_OVERLAP": 409,
    "ERR_UPDATE_QUIET_PERIOD": 409,
    "ERR_DUPLICATE_RESOURCE": 409,
    "ERR_STALE_OFFERING_VERSION": 412,
    "ERR_INVALID_REQUEST": 400,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
