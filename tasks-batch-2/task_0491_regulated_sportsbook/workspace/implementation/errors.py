"""Error catalogue (PRD §5 / SCAFFOLD §1.6).

Each ApiError carries an error_id, an HTTP status, and a human message.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# (error_id -> http status) mapping, verbatim from PRD §5.
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_UNDERAGE": 403,
    "ERR_KYC_NOT_VERIFIED": 403,
    "ERR_RG_SELF_EXCLUDED": 403,
    "ERR_RG_COOLING_OFF": 403,
    "ERR_GEO_INELIGIBLE": 403,
    "ERR_MARKET_NOT_OPEN": 409,
    "ERR_PARLAY_COMPOSITION_INVALID": 422,
    "ERR_DUPLICATE_LEG": 422,
    "ERR_WAGER_LIMIT_EXCEEDED": 403,
    "ERR_NET_LOSS_LIMIT_EXCEEDED": 403,
    "ERR_RISK_LIMIT_EXCEEDED": 409,
    "ERR_DEPOSIT_LIMIT_EXCEEDED": 403,
    "ERR_INSUFFICIENT_FUNDS": 402,
    "ERR_WR_NOT_MET": 409,
    "ERR_PROMO_UNAVAILABLE": 409,
    "ERR_CASHOUT_UNAVAILABLE": 409,
    "ERR_LEG_ALREADY_GRADED": 409,
    "ERR_EVENT_LOCKED": 409,
    "ERR_SOD_CONFLICT": 403,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
