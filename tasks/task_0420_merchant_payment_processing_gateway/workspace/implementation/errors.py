"""Error classes and the error catalog (PRD §5 / SCAFFOLD §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Maps error_id -> http status, for convenience constructors.
_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 404,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_ENUM": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_MERCHANT_NOT_APPROVED": 409,
    "ERR_RISK_BAND_POLICY_VIOLATION": 422,
    "ERR_CAPTURE_EXCEEDS_AUTH": 422,
    "ERR_REFUND_EXCEEDS_CAPTURED": 422,
    "ERR_REFUND_BLOCKED_BY_DISPUTE": 409,
    "ERR_DISPUTE_AMOUNT_MISMATCH": 422,
    "ERR_EVIDENCE_WINDOW_CLOSED": 422,
    "ERR_REPRESENTMENT_LIMIT_REACHED": 422,
    "ERR_FUNDING_DATE_NOT_REACHED": 409,
    "ERR_PAYOUT_DATE_NOT_REACHED": 409,
    "ERR_INSUFFICIENT_BALANCE": 422,
    "ERR_STALE_MERCHANT_VERSION": 412,
    "ERR_FEE_PLAN_INCOMPLETE": 422,
    "ERR_NO_ELIGIBLE_CHARGES": 409,
    "ERR_RESOLVE_OUTCOME_INVALID": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, _CATALOG[error_id], message)
