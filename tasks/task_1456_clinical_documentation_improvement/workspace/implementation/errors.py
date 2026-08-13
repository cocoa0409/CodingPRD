"""Error classes and error ID constants per SCAFFOLD errors table."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# Error catalog (id -> http status), per PRD section 5.
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_PROGRAM_NOT_ACTIVE": 409,
    "ERR_OPEN_CASES_REMAIN": 409,
    "ERR_CASE_NOT_REVIEWABLE": 409,
    "ERR_REVIEW_ALREADY_ACTIVE": 409,
    "ERR_REVIEW_NOT_ACTIVE": 409,
    "ERR_UNRESOLVED_QUERY_EXISTS": 409,
    "ERR_LEADING_LANGUAGE": 422,
    "ERR_PROVIDER_NOT_IN_PROGRAM": 422,
    "ERR_NOT_QUERY_RECIPIENT": 403,
    "ERR_PROVIDER_UNDER_INTENSIVE_REVIEW": 403,
    "ERR_CASE_NOT_DISCHARGED": 422,
    "ERR_DRG_MISMATCH": 409,
    "ERR_DENIAL_TARGET_UNMET": 422,
    "ERR_DEFAULT_POLICY_CONFLICT": 409,
    "ERR_OPEN_REVIEW_EXISTS": 409,
}


def raise_error(error_id, message):
    raise ApiError(error_id, ERRORS[error_id], message)
