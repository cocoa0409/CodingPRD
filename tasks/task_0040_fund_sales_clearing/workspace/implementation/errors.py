"""Error catalog and APIError exception."""


class APIError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error catalog: error_id -> http_status (per PRD §5)
ERROR_CATALOG = {
    "ERR_AUTH_HEADERS_MISSING": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_IDEMPOTENCY_REPLAY": 409,
    "ERR_SOD_VIOLATION_SHELF": 403,
    "ERR_SOD_VIOLATION_NAV": 403,
    "ERR_SOD_VIOLATION_RECON": 403,
    "ERR_KYC_NOT_APPROVED": 422,
    "ERR_SUITABILITY_MISMATCH": 422,
    "ERR_REGION_RESTRICTED": 422,
    "ERR_CONVERSION_INVALID_TARGET": 422,
    "ERR_CANCEL_WINDOW_CLOSED": 409,
    "ERR_NAV_T_PLUS_1_NOT_ELAPSED": 409,
    "ERR_NAV_ALREADY_PUBLISHED": 409,
    "ERR_DIVIDEND_DATE_INVALID": 422,
    "ERR_ORDER_LIMIT_VIOLATED": 422,
    "ERR_FEE_TIERS_INVALID": 422,
    "ERR_INSUFFICIENT_CASH": 422,
    "ERR_INSUFFICIENT_SHARES": 422,
    "ERR_RECONCILIATION_INVARIANT_BROKEN": 409,
    "ERR_FUND_HAS_HOLDERS": 409,
    "ERR_WAIVE_NOT_ALLOWED": 422,
    "ERR_FUND_SUSPENDED": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_CLOCK_NOT_MONOTONIC": 422,
    # Generic input-validation fallback
    "ERR_VALIDATION": 422,
}


def err(error_id: str, message: str = "") -> APIError:
    http = ERROR_CATALOG.get(error_id, 422)
    return APIError(error_id, message or error_id, http)
