"""Error catalogue (PRD section 5 - 53 declared codes) and the ApiError exception."""

# error_id -> HTTP status
ERROR_STATUS = {
    # authentication, authorization, shape
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_BANNER_NOT_FOUND": 404,
    "ERR_SITE_NOT_FOUND": 404,
    "ERR_HOUSEHOLD_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_HOUSEHOLD_LINK_NOT_FOUND": 404,
    "ERR_PROMO_EVENT_NOT_FOUND": 404,
    "ERR_POINT_CYCLE_NOT_FOUND": 404,
    "ERR_PURCHASE_TRANSACTION_NOT_FOUND": 404,
    "ERR_LEDGER_ENTRY_NOT_FOUND": 404,
    "ERR_FUEL_REDEMPTION_NOT_FOUND": 404,
    "ERR_SETTLEMENT_BATCH_NOT_FOUND": 404,
    "ERR_POINT_DISPUTE_NOT_FOUND": 404,
    "ERR_FRAUD_SIGNAL_NOT_FOUND": 404,
    # ownership, segregation of duties, authority
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SELF_APPROVAL_FORBIDDEN": 403,
    "ERR_TIER_AUTHORITY_REQUIRED": 403,
    "ERR_ADJUSTMENT_EXCEEDS_AUTHORITY": 403,
    # optimistic concurrency
    "ERR_STALE_MEMBER_VERSION": 412,
    "ERR_STALE_SITE_VERSION": 412,
    # state
    "ERR_HOUSEHOLD_FROZEN": 409,
    "ERR_BANNER_SUSPENDED": 409,
    "ERR_SITE_SUSPENDED": 409,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_CYCLE_NOT_OPEN": 409,
    "ERR_CYCLE_NOT_ENDED": 409,
    "ERR_PRIOR_CYCLE_NOT_CLOSED": 409,
    # business safety
    "ERR_TRANSFER_FRAUD_LOCK": 403,
    "ERR_ALT_ID_MISMATCH": 422,
    "ERR_CROSS_BANNER_LINK_REQUIRED": 422,
    # business temporal
    "ERR_PROMO_WINDOW_CONFLICT": 409,
    "ERR_BATCH_PERIOD_OVERLAP": 409,
    "ERR_OPEN_BATCH_LIMIT": 409,
    # business referential
    "ERR_RECIPIENT_NOT_IN_HOUSEHOLD": 422,
    "ERR_DISPUTE_ENTRY_MEMBER_MISMATCH": 422,
    "ERR_GROCERY_SITE_REQUIRED": 422,
    "ERR_FUEL_SITE_REQUIRED": 422,
    "ERR_PARTNER_SITE_REQUIRED": 422,
    # business constraint
    "ERR_INVALID_TRANSFER_AMOUNT": 422,
    "ERR_TRANSFER_LIMIT_EXCEEDED": 409,
    "ERR_NEXT_CYCLE_NOT_DEFINED": 422,
    "ERR_ALT_ID_DUPLICATE": 409,
    "ERR_HOUSEHOLD_CODE_DUPLICATE": 409,
    "ERR_CYCLE_MONTH_DUPLICATE": 409,
    "ERR_DUPLICATE_ACTIVE_LINK": 409,
    "ERR_PRIMARY_LINK_EXISTS": 409,
    "ERR_SUPERSEDE_CHAIN_TOO_LONG": 409,
    "ERR_BELOW_MIN_REDEMPTION": 422,
    # business fiscal
    "ERR_INSUFFICIENT_POINTS": 422,
    "ERR_GALLONS_EXCEED_AUTHORIZATION": 422,
    "ERR_NO_SETTLEABLE_GALLONS": 422,
    # infrastructure fallbacks (not part of the declared catalogue)
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def bad_request(message="request payload is malformed"):
    return ApiError("ERR_INVALID_REQUEST", message)
