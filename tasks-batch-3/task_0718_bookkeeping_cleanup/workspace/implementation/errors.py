class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Convenience constructors keyed by the scaffold/PRD error catalog.
ERRORS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_FORBIDDEN_FOR_ROLE": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_ENTRY_OUT_OF_PERIOD": 409,
    "ERR_ACCOUNT_EXCLUDED": 409,
    "ERR_ENTRY_SETTLED": 409,
    "ERR_ACCOUNT_RECONCILED": 409,
    "ERR_NO_POSTED_ENTRIES": 409,
    "ERR_NO_CATEGORIZED_ACCOUNTS": 409,
    "ERR_UNPOSTED_ENTRIES": 409,
    "ERR_NOT_BANK_ACCOUNT": 409,
    "ERR_OPEN_RECON_ITEMS": 409,
    "ERR_RECON_OUT_OF_BALANCE": 409,
    "ERR_BANK_NOT_RECONCILED": 409,
    "ERR_OPEN_DIFF_EXCEPTION": 409,
    "ERR_RECON_NOT_IN_BALANCE": 409,
    "ERR_BLOCKING_EXCEPTIONS_OPEN": 409,
    "ERR_PHASE_WEIGHTS_INVALID": 409,
    "ERR_PHASE_ORDER": 409,
    "ERR_SCOPE_NOT_LOCKED": 409,
    "ERR_BILLING_NOT_SETTLED": 409,
    "ERR_TAX_NOT_HANDED_OFF": 409,
    "ERR_PAID_INVOICES_EXIST": 409,
    "ERR_CANNOT_WAIVE_DIFF": 409,
    "ERR_DUPLICATE_ACCOUNT_CODE": 409,
    "ERR_STALE_ENGAGEMENT_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)
