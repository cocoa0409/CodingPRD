"""Error classes and error-id / HTTP-status catalogue.

Every error_id and its HTTP status is taken verbatim from PRD §5 Error Code
Catalogue and SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id -> http status (PRD §5)
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_SITE_OWNER_MISMATCH": 409,
    "ERR_MEMBERSHIP_NOT_ACTIVE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_TECH_NOT_CERTIFIED": 422,
    "ERR_REFRIGERANT_BALANCE": 422,
    "ERR_REFRIGERANT_NOT_EVACUATED": 422,
    "ERR_TECH_REGION_TRADE_MISMATCH": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_TECH_DOUBLE_BOOKED": 409,
    "ERR_TECH_DAILY_CAPACITY": 409,
    "ERR_OFFER_ALREADY_OPEN": 409,
    "ERR_OFFER_EXPIRED": 409,
    "ERR_APPROVAL_EXCEEDS_CLAIM": 422,
    "ERR_CLAIM_ORIGIN_INVALID": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_VALIDATION": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
