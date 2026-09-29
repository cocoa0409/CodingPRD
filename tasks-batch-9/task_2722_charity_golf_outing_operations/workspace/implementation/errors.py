"""Error catalog and the ApiError exception (PRD section 5)."""

ERROR_STATUS = {
    # --- authentication and authorization ---
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- request schema ---
    "ERR_INVALID_REQUEST": 422,
    "ERR_RECEIPT_SUBJECT_AMBIGUOUS": 422,
    "ERR_RAFFLE_NOT_DEDUCTIBLE": 422,
    # --- existence ---
    "ERR_OUTING_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_TIER_NOT_FOUND": 404,
    "ERR_REGISTRATION_NOT_FOUND": 404,
    "ERR_PLAYER_NOT_FOUND": 404,
    "ERR_TEAM_NOT_FOUND": 404,
    "ERR_ASSET_NOT_FOUND": 404,
    "ERR_ALLOCATION_NOT_FOUND": 404,
    "ERR_CONTEST_NOT_FOUND": 404,
    "ERR_ITEM_NOT_FOUND": 404,
    "ERR_RECEIPT_NOT_FOUND": 404,
    # --- referential integrity ---
    "ERR_CROSS_OUTING_REFERENCE": 409,
    "ERR_CONTRACT_ALREADY_EXISTS": 409,
    "ERR_TIER_CODE_DUPLICATE": 409,
    "ERR_PLAYER_ALREADY_ASSIGNED": 409,
    "ERR_PLAYER_SLOTS_EXCEEDED": 409,
    "ERR_ASSET_TYPE_MISMATCH": 409,
    "ERR_ALLOCATION_NOT_ENTITLED": 409,
    "ERR_REGISTRATION_NOT_REVENUE_RECOGNIZED": 409,
    "ERR_NO_PACKAGE_TIER": 409,
    # --- state ---
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_REGISTRATION_CLOSED": 409,
    "ERR_RECEIPT_IMMUTABLE": 409,
    "ERR_CONTRACT_NOT_SIGNED": 409,
    "ERR_INSURANCE_NOT_BOUND": 409,
    "ERR_TEAM_INCOMPLETE": 409,
    "ERR_MISSING_TEE_ASSIGNMENT": 409,
    "ERR_MISSING_SCORES": 409,
    "ERR_NO_RAIN_DATE_TERMS": 409,
    "ERR_AMATEUR_CASH_CAP_EXCEEDED": 409,
    "ERR_UNRECEIPTED_ITEMS_REMAIN": 409,
    "ERR_ASSET_WITHDRAWN": 409,
    "ERR_ASSET_OCCUPIED": 409,
    # --- optimistic concurrency ---
    "ERR_STALE_TEAM_VERSION": 412,
    "ERR_STALE_REGISTRATION_VERSION": 412,
    "ERR_STALE_OUTING_VERSION": 412,
    # --- temporal ---
    "ERR_TEE_SLOT_CONFLICT": 409,
    "ERR_WAVE_WINDOW_VIOLATION": 409,
    "ERR_CART_DOUBLE_BOOKED": 409,
    "ERR_SERVICE_WINDOW_CONFLICT": 409,
    "ERR_FULFILLMENT_WINDOW_ELAPSED": 409,
    "ERR_CANCELLATION_NOTICE_VIOLATION": 409,
    # --- capacity and constraint ---
    "ERR_ASSET_CAPACITY_EXCEEDED": 409,
    "ERR_EXCLUSIVE_ASSET_CONFLICT": 409,
    "ERR_CART_ALLOWANCE_EXCEEDED": 409,
    "ERR_TIER_INVENTORY_EXHAUSTED": 409,
    "ERR_TEAM_SIZE_INVALID": 409,
    "ERR_CONTEST_HOLE_CONFLICT": 409,
    "ERR_DUPLICATE_RECEIPT": 409,
    "ERR_MAX_REOPENS_EXCEEDED": 409,
    # --- fiscal ---
    "ERR_PAYMENT_AMOUNT_MISMATCH": 402,
    "ERR_INSUFFICIENT_BID": 402,
    "ERR_REFUND_EXCEEDS_PAYMENT": 409,
    "ERR_PRIZE_POOL_UNFUNDED": 409,
    "ERR_NEGATIVE_NET_PROCEEDS": 409,
    "ERR_REMITTANCE_AMOUNT_MISMATCH": 402,
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline; rendered by the Flask handler."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)
