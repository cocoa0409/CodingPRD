"""Error catalogue (PRD §5). Each ApiError carries error_id, message, http_status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error id -> http status (PRD §5 catalogue)
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_LISTING_VERSION": 412,
    "ERR_STALE_OFFER_VERSION": 412,
    "ERR_MEMBER_NOT_ACTIVE": 403,
    "ERR_SPOT_NOT_POLICE_VERIFIED": 422,
    "ERR_SELLER_NOT_PHONE_VERIFIED": 422,
    "ERR_OUTSIDE_SPOT_HOURS": 422,
    "ERR_SPOT_TIME_CONFLICT": 409,
    "ERR_NOT_YOUR_TURN": 409,
    "ERR_MAX_ROUNDS_REACHED": 409,
    "ERR_ACTIVE_LISTING_LIMIT": 409,
    "ERR_MAX_RENEWALS_REACHED": 409,
    "ERR_PRICE_EXCEEDS_CATEGORY_CAP": 422,
    "ERR_NOT_CONVERSATION_PARTICIPANT": 403,
    "ERR_CANNOT_TRADE_OWN_LISTING": 422,
    "ERR_FLOOR_ABOVE_ASK": 422,
    "ERR_INVALID_REQUEST": 400,
    "ERR_BAN_THRESHOLD_NOT_MET": 409,
    "ERR_VERIFICATION_CODE_MISMATCH": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
