"""Error classes and error-ID constants.

Every error_id and its HTTP status is taken verbatim from PRD §5 / scaffold §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id -> http_status (PRD §5 Error Code Catalogue)
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_APPLICATION_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_COSIGNER_NOT_CONSENTED": 409,
    "ERR_RELEASE_NOT_ELIGIBLE": 409,
    "ERR_OFFER_EXPIRED": 409,
    "ERR_NO_MATCHING_RATE": 422,
    "ERR_NO_LOCKED_OFFER": 409,
    "ERR_DTI_EXCEEDED": 422,
    "ERR_NO_ELIGIBLE_POOL": 422,
    "ERR_PAYOFF_EXCEEDS_PRINCIPAL": 422,
    "ERR_FORBEARANCE_TERM_INVALID": 422,
    "ERR_INVALID_REQUEST": 400,
    "ERR_COSIGNER_ALREADY_ATTACHED": 409,
    "ERR_DUPLICATE_KEY": 409,
    "ERR_FORBEARANCE_ALREADY_ACTIVE": 409,
    "ERR_PAGINATION_INVALID": 400,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP[error_id], message)
