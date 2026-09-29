"""Error catalogue (36 ids) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGE.get(error_id, error_id)


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_FORBIDDEN_RESOURCE_SCOPE": 403,
    "ERR_BUYER_NOT_FOUND": 404,
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_SUPPLIER_NOT_FOUND": 404,
    "ERR_BANK_ACCOUNT_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_DISPUTE_NOT_FOUND": 404,
    "ERR_OFFER_NOT_FOUND": 404,
    "ERR_FUNDER_NOT_FOUND": 404,
    "ERR_EARLY_PAYMENT_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_STALE_INVOICE_VERSION": 412,
    "ERR_STALE_OFFER_VERSION": 412,
    "ERR_PROGRAM_NOT_OPEN": 409,
    "ERR_SESSION_NOT_LIVE": 409,
    "ERR_SESSION_WINDOW_CONFLICT": 409,
    "ERR_FILE_TOTALS_MISMATCH": 422,
    "ERR_INVOICE_DISPUTE_SUPPRESSED": 409,
    "ERR_SUPPLIER_NOT_PAYMENT_READY": 409,
    "ERR_SUPPLIER_SANCTIONS_HOLD": 403,
    "ERR_MICRO_DEPOSIT_ATTEMPTS_EXHAUSTED": 409,
    "ERR_APR_OUT_OF_PROGRAM_BOUNDS": 422,
    "ERR_COUNTER_ROUNDS_EXHAUSTED": 409,
    "ERR_ACCEPTANCE_WINDOW_CLOSED": 409,
    "ERR_INSUFFICIENT_DAYS_EARLY": 422,
    "ERR_CONCENTRATION_CAP_EXCEEDED": 409,
    "ERR_BUYER_CREDIT_LIMIT_EXCEEDED": 402,
    "ERR_SELF_FUNDING_DISABLED": 409,
    "ERR_FUNDER_CAPITAL_OVERCOMMITTED": 409,
    "ERR_NO_ELIGIBLE_FUNDER": 422,
    "ERR_RECLASS_OVERRIDE_REASON_REQUIRED": 422,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or carry an unrecognised role.",
    "ERR_UNAUTHORIZED": "The acting role is not permitted to perform this operation.",
    "ERR_INVALID_REQUEST": "The request payload or query string is malformed.",
    "ERR_FORBIDDEN_RESOURCE_SCOPE": "The addressed resource lies outside the caller's scope.",
    "ERR_BUYER_NOT_FOUND": "Buyer not found.",
    "ERR_PROGRAM_NOT_FOUND": "Buyer programme not found.",
    "ERR_SESSION_NOT_FOUND": "Auction session not found.",
    "ERR_SUPPLIER_NOT_FOUND": "Supplier not found.",
    "ERR_BANK_ACCOUNT_NOT_FOUND": "Bank account not found.",
    "ERR_INVOICE_NOT_FOUND": "Invoice not found.",
    "ERR_DISPUTE_NOT_FOUND": "Dispute not found.",
    "ERR_OFFER_NOT_FOUND": "Discount offer not found.",
    "ERR_FUNDER_NOT_FOUND": "Funder not found.",
    "ERR_EARLY_PAYMENT_NOT_FOUND": "Early payment not found.",
    "ERR_INVALID_STATE": "The addressed resource does not satisfy the preconditions of this transition.",
    "ERR_ALREADY_TERMINAL": "The addressed resource has already reached a terminal state.",
    "ERR_STALE_INVOICE_VERSION": "The supplied expected_invoice_version does not match the stored invoice version.",
    "ERR_STALE_OFFER_VERSION": "The supplied expected_offer_version does not match the stored offer version.",
    "ERR_PROGRAM_NOT_OPEN": "The governing buyer programme is not OPEN.",
    "ERR_SESSION_NOT_LIVE": "The governing auction session is not LIVE.",
    "ERR_SESSION_WINDOW_CONFLICT": "The requested session window conflicts with an existing session.",
    "ERR_FILE_TOTALS_MISMATCH": "Declared control totals do not match the computed totals.",
    "ERR_INVOICE_DISPUTE_SUPPRESSED": "The invoice is suppressed by an open dispute.",
    "ERR_SUPPLIER_NOT_PAYMENT_READY": "The supplier is not payment ready.",
    "ERR_SUPPLIER_SANCTIONS_HOLD": "The supplier is under a sanctions hold.",
    "ERR_MICRO_DEPOSIT_ATTEMPTS_EXHAUSTED": "The micro-deposit attempt budget is exhausted.",
    "ERR_APR_OUT_OF_PROGRAM_BOUNDS": "The APR lies outside the programme's bounds.",
    "ERR_COUNTER_ROUNDS_EXHAUSTED": "The counter round budget is exhausted.",
    "ERR_ACCEPTANCE_WINDOW_CLOSED": "The acceptance window has closed.",
    "ERR_INSUFFICIENT_DAYS_EARLY": "The payment is not early enough for this programme.",
    "ERR_CONCENTRATION_CAP_EXCEEDED": "The supplier concentration cap would be exceeded.",
    "ERR_BUYER_CREDIT_LIMIT_EXCEEDED": "The buyer's self-funding credit limit would be exceeded.",
    "ERR_SELF_FUNDING_DISABLED": "Self funding is disabled for this buyer.",
    "ERR_FUNDER_CAPITAL_OVERCOMMITTED": "The commitment would breach the funder's capital limit.",
    "ERR_NO_ELIGIBLE_FUNDER": "No eligible funder can fund this payment.",
    "ERR_RECLASS_OVERRIDE_REASON_REQUIRED": "An override_reason is required to diverge from the default classification.",
}


def api_error(error_id, message=None):
    return ApiError(error_id, message)
