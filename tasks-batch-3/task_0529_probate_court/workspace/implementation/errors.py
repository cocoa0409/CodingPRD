"""Error catalogue and the APIError exception."""


class APIError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue: error_id -> http status
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REFERENCE": 422,
    "ERR_MISSING_FIELD": 400,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_CROSS_ENTITY_STATE": 409,
    "ERR_WILL_NOT_LODGED": 409,
    "ERR_BOND_NOT_APPROVED": 409,
    "ERR_BOND_INSUFFICIENT": 409,
    "ERR_CLAIM_PERIOD_CLOSED": 409,
    "ERR_ALLOWED_AMOUNT_INVALID": 409,
    "ERR_CLAIM_PRIORITY_VIOLATION": 409,
    "ERR_INSUFFICIENT_MARSHALED_FUNDS": 409,
    "ERR_DISTRIBUTION_EXCEEDS_RESIDUE": 409,
    "ERR_CLAIMS_UNPAID": 409,
    "ERR_ACCOUNTING_UNBALANCED": 409,
    "ERR_COURTROOM_CONFLICT": 409,
    "ERR_JUDGE_CALENDAR_CONFLICT": 409,
}


def err(error_id, message=None):
    return APIError(error_id, ERRORS[error_id], message)
