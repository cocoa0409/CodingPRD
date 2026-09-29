"""Error catalogue for the convenience-store foodservice program API.

Every error id and its HTTP status is taken verbatim from PRD section 5 /
SCAFFOLD 1.6.  Nothing here is invented.
"""

ERROR_HTTP = {
    # --- authentication / authorization ---
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_ORDER_NOT_OWNED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_LOCKOUT_REQUIRES_SAFETY_LEAD": 403,
    # --- request shape ---
    "ERR_INVALID_REQUEST": 400,
    # --- not found ---
    "ERR_STORE_NOT_FOUND": 404,
    "ERR_HOLDING_UNIT_NOT_FOUND": 404,
    "ERR_MENU_ITEM_NOT_FOUND": 404,
    "ERR_MODIFIER_OPTION_NOT_FOUND": 404,
    "ERR_PROMOTION_RULE_NOT_FOUND": 404,
    "ERR_LOYALTY_ACCOUNT_NOT_FOUND": 404,
    "ERR_STAFFING_PLAN_NOT_FOUND": 404,
    "ERR_PRODUCTION_BATCH_NOT_FOUND": 404,
    "ERR_TEMPERATURE_LOG_NOT_FOUND": 404,
    "ERR_CORRECTIVE_ACTION_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_ORDER_LINE_NOT_FOUND": 404,
    "ERR_KITCHEN_TICKET_NOT_FOUND": 404,
    # --- uniqueness ---
    "ERR_DUPLICATE_CODE": 409,
    # --- optimistic concurrency ---
    "ERR_STALE_STORE_VERSION": 412,
    "ERR_STALE_BATCH_VERSION": 412,
    # --- state machine guards ---
    "ERR_ORDER_NOT_DRAFT": 409,
    "ERR_ORDER_PRODUCTION_STATE_INVALID": 409,
    "ERR_ORDER_SETTLEMENT_STATE_INVALID": 409,
    "ERR_TICKET_STATE_INVALID": 409,
    "ERR_BATCH_STATE_INVALID": 409,
    "ERR_PLAN_STATE_INVALID": 409,
    "ERR_PLAN_LOCKED": 409,
    "ERR_UNIT_NOT_IMPAIRED": 409,
    "ERR_ACTION_ALREADY_VERIFIED": 409,
    "ERR_ORDER_NOT_AUTHORIZED": 409,
    "ERR_ORDER_NOT_REWORKABLE": 409,
    # --- business rules: capture and menu ---
    "ERR_ORDER_EMPTY": 422,
    "ERR_MODIFIER_NOT_FOR_ITEM": 422,
    "ERR_MODIFIER_LIMIT_EXCEEDED": 422,
    "ERR_MENU_ITEM_NOT_IN_DAYPART": 422,
    "ERR_ITEM_NOT_CATERING_ELIGIBLE": 422,
    "ERR_ORDER_MINIMUM_NOT_MET": 422,
    "ERR_DAYPART_PLAN_NOT_PUBLISHED": 409,
    "ERR_DAYPART_NOT_DUE": 409,
    # --- business rules: pickup windows ---
    "ERR_PICKUP_WINDOW_NOT_ALLOWED": 422,
    "ERR_PICKUP_WINDOW_REQUIRED": 422,
    "ERR_PICKUP_WINDOW_INVALID": 422,
    "ERR_PREORDER_LEAD_TIME_TOO_SHORT": 422,
    "ERR_PICKUP_WINDOW_ELAPSED": 409,
    "ERR_PICKUP_WINDOW_FULL": 409,
    "ERR_PICKUP_WINDOW_NOT_OPEN": 409,
    # --- business rules: production and safety ---
    "ERR_SLOT_INDEX_OUT_OF_RANGE": 422,
    "ERR_UNIT_SLOT_CONFLICT": 409,
    "ERR_HOLDING_UNIT_NOT_OPERATIONAL": 409,
    "ERR_HOT_CASE_CAPACITY_EXCEEDED": 409,
    "ERR_ITEM_NOT_PAR_BAKED": 422,
    "ERR_INSUFFICIENT_BATCH_QTY": 422,
    "ERR_BATCH_HOLD_EXPIRED": 422,
    "ERR_DISCARD_QTY_EXCEEDS_REMAINING": 422,
    "ERR_RESERVED_DISCARD_REASON": 422,
    "ERR_TEMP_READING_OUT_OF_SENSOR_RANGE": 422,
    # --- business rules: loyalty and clock ---
    "ERR_POINTS_BALANCE_NEGATIVE": 422,
    "ERR_CLOCK_REGRESSION": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing, blank or name an unknown role.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not permitted to call this endpoint.",
    "ERR_ORDER_NOT_OWNED": "The acting customer does not own this order.",
    "ERR_SEGREGATION_OF_DUTIES": "A second, different actor is required for this operation.",
    "ERR_LOCKOUT_REQUIRES_SAFETY_LEAD": "Only a FoodSafetyLead may clear a locked-out holding unit.",
    "ERR_INVALID_REQUEST": "The request body is malformed.",
    "ERR_DUPLICATE_CODE": "The supplied code already exists.",
    "ERR_STALE_STORE_VERSION": "The supplied expected_store_version does not match the store's current version.",
    "ERR_STALE_BATCH_VERSION": "The supplied expected_batch_version does not match the batch's current version.",
}


class ApiError(Exception):
    """Domain error carrying the scaffold-declared error id and HTTP status."""

    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )
