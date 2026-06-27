"""Error catalogue (PRD 5). Every error_id and HTTP status comes from the PRD."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id -> http status, per PRD 5 / scaffold 1.6
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_CLIENT_SUSPENDED": 409,
    "ERR_NO_DOCUMENT": 409,
    "ERR_SERVER_SUSPENDED": 409,
    "ERR_SERVER_AT_CAPACITY": 409,
    "ERR_ASSIGNMENT_NOT_ACTIVE": 409,
    "ERR_ASSIGNMENT_SUPERSEDED": 409,
    "ERR_OUTSIDE_TERRITORY": 409,
    "ERR_NO_CONTACT_ATTEMPT": 409,
    "ERR_DILIGENCE_NOT_MET": 409,
    "ERR_DEADLINE_PASSED": 409,
    "ERR_STAKEOUT_OVERLAP": 409,
    "ERR_AFFIDAVIT_NOT_NOTARIZED": 409,
    "ERR_SEGREGATION_VIOLATION": 409,
    "ERR_EFILE_NOT_ENABLED": 409,
    "ERR_FILING_WINDOW_FULL": 409,
    "ERR_NO_CANDIDATE_ADDRESS": 409,
    "ERR_ADDRESS_NOT_CANDIDATE": 409,
    "ERR_INSUFFICIENT_FUNDS": 402,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
