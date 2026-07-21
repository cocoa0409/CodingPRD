"""Error catalog (SCAFFOLD §1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_CLAIM_OWNER": 403,
    "ERR_VALIDATION": 400,
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_OFFER_NOT_FOUND": 404,
    "ERR_CLAIMANT_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_RECEIPT_NOT_FOUND": 404,
    "ERR_PAYOUT_NOT_FOUND": 404,
    "ERR_CARD_NOT_FOUND": 404,
    "ERR_FRAUD_CASE_NOT_FOUND": 404,
    "ERR_PROGRAM_NOT_ACTIVE": 409,
    "ERR_OFFER_NOT_PUBLISHED": 409,
    "ERR_OFFER_WINDOW_OVERLAP": 409,
    "ERR_CLAIM_NOT_DRAFT": 409,
    "ERR_CLAIM_NOT_REVIEWABLE": 409,
    "ERR_CLAIM_ALREADY_TERMINAL": 409,
    "ERR_INVALID_TRANSITION": 409,
    "ERR_PAYOUT_NOT_RELEASABLE": 409,
    "ERR_PAYOUT_ALREADY_EXISTS": 409,
    "ERR_NOT_CHECK_PAYOUT": 409,
    "ERR_CARD_NOT_ACTIVE": 409,
    "ERR_CLAIMANT_BLOCKED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_CLAIM_WINDOW_EXPIRED": 422,
    "ERR_PURCHASE_OUTSIDE_OFFER_WINDOW": 422,
    "ERR_OFFER_WINDOW_CLOSED": 422,
    "ERR_DUPLICATE_RECEIPT_SERIAL": 409,
    "ERR_CHANNEL_MISMATCH": 422,
    "ERR_CLAIM_CAP_EXCEEDED": 409,
    "ERR_NO_VALIDATED_RECEIPT": 422,
    "ERR_RECEIPT_LIMIT_EXCEEDED": 422,
    "ERR_APPEAL_WINDOW_EXPIRED": 422,
    "ERR_APPEAL_LIMIT_REACHED": 409,
    "ERR_BUDGET_EXCEEDED": 409,
    "ERR_BUDGET_ADJUSTMENT_INVALID": 422,
    "ERR_BELOW_MIN_PAYOUT": 422,
    "ERR_INSUFFICIENT_CARD_BALANCE": 422,
    "ERR_STALE_CLAIM_VERSION": 412,
    "ERR_STALE_PROGRAM_VERSION": 412,
}

_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or invalid authentication headers.",
    "ERR_UNAUTHORIZED": "The acting role may not invoke this operation.",
    "ERR_NOT_CLAIM_OWNER": "The acting principal does not own this claim.",
    "ERR_VALIDATION": "The request body failed shape validation.",
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP[error_id], message)
