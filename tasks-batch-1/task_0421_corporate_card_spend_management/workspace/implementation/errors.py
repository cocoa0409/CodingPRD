"""Error catalog and the ApiError exception type.

Error IDs and HTTP statuses are taken verbatim from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- auth ---
ERR_MISSING_USER_CONTEXT = "ERR_MISSING_USER_CONTEXT"   # 400
ERR_FORBIDDEN_FOR_ROLE = "ERR_FORBIDDEN_FOR_ROLE"       # 403
ERR_SELF_APPROVAL = "ERR_SELF_APPROVAL"                 # 403

# --- existence / validation ---
ERR_NOT_FOUND = "ERR_NOT_FOUND"                         # 404
ERR_VALIDATION = "ERR_VALIDATION"                       # 422
ERR_INVALID_AMOUNT = "ERR_INVALID_AMOUNT"               # 422
ERR_DUPLICATE_EMAIL = "ERR_DUPLICATE_EMAIL"             # 409
ERR_DUPLICATE_GL_CODE = "ERR_DUPLICATE_GL_CODE"         # 409

# --- state ---
ERR_INVALID_STATE = "ERR_INVALID_STATE"                 # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                 # 412

# --- company / card spend gating ---
ERR_COMPANY_SUSPENDED = "ERR_COMPANY_SUSPENDED"         # 409
ERR_MCC_BLOCKED = "ERR_MCC_BLOCKED"                     # 409
ERR_CARD_NOT_ACTIVE = "ERR_CARD_NOT_ACTIVE"             # 409
ERR_PER_TXN_LIMIT_EXCEEDED = "ERR_PER_TXN_LIMIT_EXCEEDED"  # 409
ERR_CARD_LIMIT_EXCEEDED = "ERR_CARD_LIMIT_EXCEEDED"     # 409
ERR_INSUFFICIENT_CREDIT = "ERR_INSUFFICIENT_CREDIT"     # 402
ERR_CARD_HAS_OPEN_AUTH = "ERR_CARD_HAS_OPEN_AUTH"       # 409

# --- review / approval ---
ERR_GL_CODE_REQUIRED = "ERR_GL_CODE_REQUIRED"           # 409
ERR_APPROVAL_REQUIRED = "ERR_APPROVAL_REQUIRED"         # 409
ERR_APPROVAL_NOT_NEEDED = "ERR_APPROVAL_NOT_NEEDED"     # 409
ERR_RECEIPT_REQUIRED = "ERR_RECEIPT_REQUIRED"           # 409

# --- statement / repayment / reward ---
ERR_CLOCK_NOT_SET = "ERR_CLOCK_NOT_SET"                 # 409
ERR_INSUFFICIENT_REWARD_BALANCE = "ERR_INSUFFICIENT_REWARD_BALANCE"  # 409

# --- spend-authorization temporal overlap ---
ERR_AUTH_WINDOW_OVERLAP = "ERR_AUTH_WINDOW_OVERLAP"     # 409
ERR_AUTH_WINDOW_TOO_CLOSE = "ERR_AUTH_WINDOW_TOO_CLOSE"  # 409


# error_id -> http status, used by helpers that raise without a literal status
HTTP_STATUS = {
    ERR_MISSING_USER_CONTEXT: 400,
    ERR_FORBIDDEN_FOR_ROLE: 403,
    ERR_SELF_APPROVAL: 403,
    ERR_NOT_FOUND: 404,
    ERR_VALIDATION: 422,
    ERR_INVALID_AMOUNT: 422,
    ERR_DUPLICATE_EMAIL: 409,
    ERR_DUPLICATE_GL_CODE: 409,
    ERR_INVALID_STATE: 409,
    ERR_STALE_VERSION: 412,
    ERR_COMPANY_SUSPENDED: 409,
    ERR_MCC_BLOCKED: 409,
    ERR_CARD_NOT_ACTIVE: 409,
    ERR_PER_TXN_LIMIT_EXCEEDED: 409,
    ERR_CARD_LIMIT_EXCEEDED: 409,
    ERR_INSUFFICIENT_CREDIT: 402,
    ERR_CARD_HAS_OPEN_AUTH: 409,
    ERR_GL_CODE_REQUIRED: 409,
    ERR_APPROVAL_REQUIRED: 409,
    ERR_APPROVAL_NOT_NEEDED: 409,
    ERR_RECEIPT_REQUIRED: 409,
    ERR_CLOCK_NOT_SET: 409,
    ERR_INSUFFICIENT_REWARD_BALANCE: 409,
    ERR_AUTH_WINDOW_OVERLAP: 409,
    ERR_AUTH_WINDOW_TOO_CLOSE: 409,
}


def err(error_id, message=None):
    return ApiError(error_id, HTTP_STATUS[error_id], message)
