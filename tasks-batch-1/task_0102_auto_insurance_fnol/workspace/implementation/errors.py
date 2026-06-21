"""Error catalog and the ApiError exception (scaffold §1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (id -> http status). Exact ids/codes from PRD §5.
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_CLAIM_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_SENIOR_TIER_REQUIRED": 409,
    "ERR_DUPLICATE_COVERAGE": 409,
    "ERR_DUPLICATE_INSURED_PARTY": 409,
    "ERR_NO_SUBMITTED_ESTIMATE": 409,
    "ERR_NOT_A_TOTAL_LOSS": 409,
    "ERR_NO_RECOVERABLE_AMOUNT": 409,
    "ERR_INVALID_RENTAL_INTERVAL": 422,
    "ERR_RECOVERY_EXCEEDS_DEMAND": 409,
    "ERR_NO_SETTLEMENT_AMOUNT": 409,
    "ERR_RENTAL_PERIOD_OVERLAP": 409,
    "ERR_POLICY_PERIOD_OVERLAP": 409,
}


def err(error_id, message=None):
    """Construct an ApiError using the cataloged HTTP status for error_id."""
    return ApiError(error_id, ERRORS.get(error_id, 400), message)
