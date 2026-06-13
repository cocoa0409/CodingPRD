"""Error catalogue (PRD §5) and the ApiError exception type.

Every error_id and its HTTP status is read verbatim from the PRD §5 table /
SCAFFOLD §1.6. No status is assumed.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id -> HTTP status, straight from PRD §5 / SCAFFOLD §1.6.
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_LICENSE_KIND_MISMATCH": 422,
    "ERR_VACCINATION_MISMATCH": 422,
    "ERR_VACCINATION_EXPIRED": 422,
    "ERR_RABIES_PROOF_REQUIRED": 422,
    "ERR_DANGEROUS_DOG_HOLD": 422,
    "ERR_ALREADY_DESIGNATED": 409,
    "ERR_KENNEL_FULL": 409,
    "ERR_LICENSE_PERIOD_OVERLAP": 409,
    "ERR_PENALTY_UNPAID": 402,
    "ERR_OWNER_DELINQUENT": 409,
    "ERR_PET_NOT_ACTIVE": 409,
    "ERR_NO_MATCH_CANDIDATE": 409,
    "ERR_VALIDATION": 400,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
