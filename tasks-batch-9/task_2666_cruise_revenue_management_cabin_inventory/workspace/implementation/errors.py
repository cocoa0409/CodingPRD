"""Error catalogue (PRD section 5) and the ApiError exception."""

ERROR_HTTP = {
    # --- auth / authorization ---
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_UNKNOWN_ROLE": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_BOOKING_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- request shape / uniqueness ---
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE_VOYAGE_CODE": 400,
    "ERR_DUPLICATE_CATEGORY_CODE": 400,
    "ERR_DUPLICATE_TIER_RANK": 400,
    "ERR_DUPLICATE_GUEST_EMAIL": 400,
    "ERR_DUPLICATE_PROMO_CODE": 400,
    # --- existence ---
    "ERR_SAILING_NOT_FOUND": 404,
    "ERR_CABIN_CATEGORY_NOT_FOUND": 404,
    "ERR_SAILING_INVENTORY_NOT_FOUND": 404,
    "ERR_FARE_RULE_NOT_FOUND": 404,
    "ERR_PROMOTION_NOT_FOUND": 404,
    "ERR_GROUP_BLOCK_NOT_FOUND": 404,
    "ERR_GUEST_NOT_FOUND": 404,
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_UPGRADE_BID_NOT_FOUND": 404,
    "ERR_ITINERARY_CHANGE_NOT_FOUND": 404,
    # --- optimistic concurrency ---
    "ERR_STALE_INVENTORY_VERSION": 412,
    "ERR_STALE_SAILING_VERSION": 412,
    # --- state ---
    "ERR_SAILING_NOT_PLANNED": 409,
    "ERR_SAILING_NOT_OPEN": 409,
    "ERR_SAILING_NOT_SUSPENDED": 409,
    "ERR_SAILING_ALREADY_SAILED": 409,
    "ERR_BOOKING_NOT_IN_OPTION": 409,
    "ERR_BOOKING_NOT_ACTIVE": 409,
    "ERR_BOOKING_NOT_AWAITING_SETTLEMENT": 409,
    "ERR_PAYMENT_STATE_INVALID": 409,
    "ERR_DEPOSIT_NOT_PAID": 409,
    "ERR_GROUP_BLOCK_NOT_TENTATIVE": 409,
    "ERR_GROUP_BLOCK_CLOSED": 409,
    "ERR_GROUP_BLOCK_NOT_DEFINITE": 409,
    "ERR_PROMOTION_NOT_SCHEDULED": 409,
    "ERR_PROMOTION_ALREADY_CLOSED": 409,
    "ERR_BID_NOT_PENDING": 409,
    "ERR_BID_NOT_COUNTERED": 409,
    "ERR_ITINERARY_CHANGE_NOT_DRAFT": 409,
    # --- business (422) ---
    "ERR_MAX_OCCUPANCY_EXCEEDED": 422,
    "ERR_BERTH_SEQUENCE_INVALID": 422,
    "ERR_OVERSELL_NOT_PERMITTED": 422,
    "ERR_NO_FARE_RULE_FOR_WINDOW": 422,
    "ERR_BID_WINDOW_CLOSED": 422,
    "ERR_REVIEW_DATE_NOT_REACHED": 422,
    "ERR_REVIEW_DATE_IN_PAST": 422,
    "ERR_FARE_WINDOW_OVERLAP": 422,
    "ERR_PROMO_CADENCE_CONFLICT": 422,
    "ERR_PROMO_WINDOW_NOT_CURRENT": 422,
    "ERR_FINAL_PAYMENT_OVERDUE": 422,
    "ERR_UPGRADE_PATH_INVALID": 422,
    "ERR_PROMO_AUDIENCE_MISMATCH": 422,
    "ERR_GROUP_BLOCK_MISMATCH": 422,
    "ERR_CATEGORY_NOT_ON_SAILING": 422,
    "ERR_POSTURE_RESTRICTED": 422,
    "ERR_POSTURE_FROZEN": 422,
    "ERR_CATEGORY_SOLD_OUT": 422,
    "ERR_GROUP_BLOCK_EXHAUSTED": 422,
    "ERR_INSUFFICIENT_GROUP_INVENTORY": 422,
    "ERR_TARGET_CATEGORY_UNAVAILABLE": 422,
    "ERR_DUPLICATE_INVENTORY": 422,
    "ERR_SUSPENSION_LIMIT_REACHED": 422,
    "ERR_MAX_COUNTER_ROUNDS_EXCEEDED": 422,
    "ERR_MAX_REVIEW_EXTENSIONS_EXCEEDED": 422,
    "ERR_SAILING_NOT_SELLABLE": 422,
    "ERR_DEPOSIT_BELOW_MINIMUM": 422,
    "ERR_PAYMENT_EXCEEDS_BALANCE": 422,
    "ERR_FINAL_PAYMENT_SHORT": 422,
    "ERR_PROMOTION_NOT_ACTIVE": 422,
    "ERR_PROMO_EXHAUSTED": 422,
    "ERR_BID_BELOW_FLOOR": 422,
    "ERR_NOT_GUARANTEE_BOOKING": 422,
}

DEFAULT_MESSAGES = {
    "ERR_MISSING_AUTH_HEADERS": "Both X-User-ID and X-User-Role headers are required.",
    "ERR_UNKNOWN_ROLE": "X-User-Role is not a recognized role.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not authorized for this endpoint.",
    "ERR_NOT_BOOKING_OWNER": "A Guest may only act on their own booking.",
    "ERR_SEGREGATION_OF_DUTIES": "The agent that created the block may not sign it definite.",
    "ERR_INVALID_REQUEST": "The request payload or query parameters are malformed.",
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline; rendered by the Flask handler."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )
