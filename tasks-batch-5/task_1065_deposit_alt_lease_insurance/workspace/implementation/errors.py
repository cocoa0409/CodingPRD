"""Error catalog and the exception type routes raise to signal an API error."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id -> http status, per SCAFFOLD.yaml `errors` / PRD §5.
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 400,
    "ERR_LANDLORD_NOT_FOUND": 404,
    "ERR_RENTER_NOT_FOUND": 404,
    "ERR_PROPERTY_NOT_FOUND": 404,
    "ERR_RENTER_ENROLLMENT_NOT_FOUND": 404,
    "ERR_POLICY_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_PAYOUT_NOT_FOUND": 404,
    "ERR_SUBROGATION_CASE_NOT_FOUND": 404,
    "ERR_RECOVERY_PAYMENT_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STATE_NOT_CONFIGURED": 422,
    "ERR_STATE_ENROLLMENT_PROHIBITED": 422,
    "ERR_PROPERTY_NOT_ACTIVE": 409,
    "ERR_LEASE_TERM_OVERLAP": 409,
    "ERR_REENROLLMENT_COOLDOWN_ACTIVE": 409,
    "ERR_FEE_EXCEEDS_STATE_CAP": 422,
    "ERR_COVERAGE_LIMIT_EXCEEDED": 422,
    "ERR_CLAIM_HAS_NO_LINE_ITEMS": 422,
    "ERR_SOD_VIOLATION": 403,
    "ERR_SUBROGATION_REQUIRES_DISBURSED_PAYOUT": 409,
    "ERR_RECOVERY_PAYMENT_EXCEEDS_BALANCE": 422,
    "ERR_STALE_POLICY_VERSION": 412,
}


def err(error_id, message=None):
    http_status = ERROR_CATALOG.get(error_id, 400)
    return ApiError(error_id, http_status, message)
