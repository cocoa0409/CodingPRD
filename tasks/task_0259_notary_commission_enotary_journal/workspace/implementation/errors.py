"""Error catalogue and the ApiError exception type.

Error IDs and HTTP statuses are taken verbatim from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error ID -> HTTP status (PRD §5 Error Code Catalogue).
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_SEGREGATION_VIOLATION": 403,
    "ERR_ENOTARY_NOT_AUTHORIZED": 409,
    "ERR_NO_SIGNER": 409,
    "ERR_NO_DOCUMENT": 409,
    "ERR_NO_NOTARIZED_DOCUMENT": 409,
    "ERR_CREDENTIAL_NOT_VERIFIED": 409,
    "ERR_CREDENTIAL_ALREADY_VERIFIED": 409,
    "ERR_SIGNER_NOT_VERIFIED": 409,
    "ERR_BOND_BELOW_MINIMUM": 409,
    "ERR_BOND_NOT_ACTIVE": 409,
    "ERR_FEE_EXCEEDS_CAP": 409,
    "ERR_RENEWAL_OUT_OF_GRACE": 409,
    "ERR_RISK_THRESHOLD_BLOCK": 409,
    "ERR_NO_CLAIM_AMOUNT": 409,
    "ERR_ENTRY_NOT_POSTED": 409,
    "ERR_SESSION_TIME_CONFLICT": 409,
    "ERR_BOND_COVERAGE_OVERLAP": 409,
    "ERR_VALIDATION": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
