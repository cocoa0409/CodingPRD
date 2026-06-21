"""Error classes and error-id constants (PRD §5 / SCAFFOLD §1.6)."""


class ApiError(Exception):
    """Carries an error_id, message, and HTTP status for the response envelope."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalogue (PRD §5 / SCAFFOLD §1.6) ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"               # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                           # 403
ERR_NOT_ACCOUNT_OWNER = "ERR_NOT_ACCOUNT_OWNER"           # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                           # 404
ERR_CUSTOMER_NOT_FOUND = "ERR_CUSTOMER_NOT_FOUND"         # 404
ERR_ACCOUNT_NOT_FOUND = "ERR_ACCOUNT_NOT_FOUND"           # 404
ERR_APY_TIER_NOT_FOUND = "ERR_APY_TIER_NOT_FOUND"         # 404
ERR_INVALID_STATE = "ERR_INVALID_STATE"                   # 409
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"   # 409
ERR_KYC_RISK_TOO_HIGH = "ERR_KYC_RISK_TOO_HIGH"           # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                   # 412
ERR_DORMANCY_NOT_DUE = "ERR_DORMANCY_NOT_DUE"             # 409
ERR_ESCHEAT_NOT_DUE = "ERR_ESCHEAT_NOT_DUE"               # 409
ERR_NONZERO_BALANCE = "ERR_NONZERO_BALANCE"               # 409
ERR_PENDING_ITEMS = "ERR_PENDING_ITEMS"                   # 409
ERR_POD_ALREADY_DESIGNATED = "ERR_POD_ALREADY_DESIGNATED"  # 409
ERR_LAST_PRIMARY_OWNER = "ERR_LAST_PRIMARY_OWNER"         # 409
ERR_INTEREST_PERIOD_OVERLAP = "ERR_INTEREST_PERIOD_OVERLAP"  # 409
ERR_DUPLICATE_STOP_PAYMENT = "ERR_DUPLICATE_STOP_PAYMENT"  # 409
ERR_STOP_EXPIRY_IN_PAST = "ERR_STOP_EXPIRY_IN_PAST"       # 422
ERR_INVALID_AMOUNT = "ERR_INVALID_AMOUNT"                 # 422
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"               # 422
