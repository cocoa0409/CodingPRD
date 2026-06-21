"""Error catalogue (PRD Section 5) and the ApiError exception class."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error ID -> HTTP status, verbatim from PRD Section 5 / SCAFFOLD §1.6.
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INVALID_REQUEST": 422,
    "ERR_DUPLICATE_RESOURCE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_ORGAN_VERSION": 412,
    "ERR_NO_FINALIZED_SCORE": 409,
    "ERR_CANDIDATE_NOT_ACTIVE": 409,
    "ERR_ABO_INCOMPATIBLE": 409,
    "ERR_POSITIVE_CROSSMATCH": 409,
    "ERR_SIZE_INCOMPATIBLE": 409,
    "ERR_OFFER_WINDOW_CLOSED": 409,
    "ERR_OFFER_WINDOW_OPEN": 409,
    "ERR_ISCHEMIA_WINDOW_CLOSED": 409,
    "ERR_DUPLICATE_OPEN_OFFER": 409,
    "ERR_NO_NEXT_CANDIDATE": 409,
    "ERR_OFFER_NOT_ACCEPTED": 409,
    "ERR_FOLLOWUP_BEFORE_TRANSPLANT": 422,
    "ERR_REPORT_SUBJECT_INVALID": 422,
    "ERR_ORGAN_TYPE_MISMATCH": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
