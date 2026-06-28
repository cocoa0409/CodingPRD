"""Error definitions for the Bill Negotiation & Subscription Manager API."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http status
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_MEMBER_SUSPENDED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_VALUE_OUT_OF_RANGE": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_LINKED_RESOURCE_STATE": 409,
    "ERR_CHARGE_IN_USE": 409,
    "ERR_AGENT_CAPACITY_EXCEEDED": 409,
    "ERR_MAX_ROUNDS_REACHED": 409,
    "ERR_MAX_DISPUTE_ROUNDS_REACHED": 409,
    "ERR_OFFER_ABOVE_BASELINE": 422,
    "ERR_REFUND_ABOVE_CLAIM": 422,
    "ERR_TRIAL_END_REQUIRED": 422,
    "ERR_NO_SAVINGS_DESTINATION": 409,
    "ERR_STALE_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_CATALOG[error_id], message)
