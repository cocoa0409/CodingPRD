"""Error catalog (PRD 5) - 41 error identifiers."""

ERROR_STATUS = {
    # Authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # Request shape
    "ERR_INVALID_REQUEST": 400,
    # Existence
    "ERR_STORE_NOT_FOUND": 404,
    "ERR_RACK_NOT_FOUND": 404,
    "ERR_CARD_NOT_FOUND": 404,
    "ERR_ISSUANCE_REQUEST_NOT_FOUND": 404,
    "ERR_BULK_ORDER_NOT_FOUND": 404,
    "ERR_ALERT_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_LISTING_NOT_FOUND": 404,
    "ERR_PERIOD_NOT_FOUND": 404,
    "ERR_LEDGER_EVENT_NOT_FOUND": 404,
    "ERR_HOLD_NOT_FOUND": 404,
    # Optimistic concurrency
    "ERR_STALE_CARD_VERSION": 412,
    "ERR_STALE_PERIOD_VERSION": 412,
    # Card guards
    "ERR_CARD_NOT_ACTIVE": 409,
    "ERR_CARD_FROZEN": 409,
    # Transition legality
    "ERR_INVALID_ISSUANCE_STATE": 409,
    "ERR_INVALID_BULK_ORDER_STATE": 409,
    "ERR_INVALID_ALERT_STATE": 409,
    "ERR_INVALID_CLAIM_STATE": 409,
    "ERR_INVALID_LISTING_STATE": 409,
    "ERR_INVALID_PERIOD_STATE": 409,
    "ERR_INVALID_HOLD_STATE": 409,
    "ERR_LEDGER_EVENT_ALREADY_REVERSED": 409,
    # Uniqueness / occupancy
    "ERR_PERIOD_OVERLAP": 409,
    "ERR_DUPLICATE_LISTING": 409,
    # Retail-floor safety
    "ERR_PACKAGING_SEAL_BROKEN": 422,
    "ERR_RACK_TAMPERED": 422,
    "ERR_STORE_FLOOR_SUSPENDED": 422,
    # Referential business rules
    "ERR_IDENTITY_VERIFICATION_REQUIRED": 422,
    "ERR_EVIDENCE_INCOMPLETE": 422,
    "ERR_ALERT_NOT_CONFIRMED": 422,
    # Temporal
    "ERR_CLAIM_WINDOW_EXPIRED": 422,
    # Quantitative limits
    "ERR_BULK_QUANTITY_LIMIT_EXCEEDED": 422,
    "ERR_EVIDENCE_ROUND_LIMIT_EXCEEDED": 422,
    # Fiscal ceilings
    "ERR_INSUFFICIENT_BALANCE": 422,
    "ERR_HOLD_CAPACITY_EXCEEDED": 422,
    "ERR_REISSUE_LIMIT_EXCEEDED": 422,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or empty.",
    "ERR_UNAUTHORIZED": "The caller's role is not authorized for this operation.",
    "ERR_SEGREGATION_OF_DUTIES": "The same operator may not perform both duties.",
    "ERR_INVALID_REQUEST": "The request is malformed.",
    "ERR_STORE_NOT_FOUND": "Retail store not found.",
    "ERR_RACK_NOT_FOUND": "Card rack not found.",
    "ERR_CARD_NOT_FOUND": "Gift card not found.",
    "ERR_ISSUANCE_REQUEST_NOT_FOUND": "Issuance request not found.",
    "ERR_BULK_ORDER_NOT_FOUND": "Bulk purchase order not found.",
    "ERR_ALERT_NOT_FOUND": "Draining alert not found.",
    "ERR_CLAIM_NOT_FOUND": "Victim claim not found.",
    "ERR_LISTING_NOT_FOUND": "Reseller listing not found.",
    "ERR_PERIOD_NOT_FOUND": "Liability period not found.",
    "ERR_LEDGER_EVENT_NOT_FOUND": "Ledger event not found.",
    "ERR_HOLD_NOT_FOUND": "Redemption hold not found.",
    "ERR_STALE_CARD_VERSION": "The supplied gift card version is stale.",
    "ERR_STALE_PERIOD_VERSION": "The supplied liability period version is stale.",
    "ERR_CARD_NOT_ACTIVE": "The gift card is not ACTIVE.",
    "ERR_CARD_FROZEN": "The gift card is FROZEN.",
    "ERR_INVALID_ISSUANCE_STATE": "The issuance request is not in a state that permits this transition.",
    "ERR_INVALID_BULK_ORDER_STATE": "The bulk purchase order is not in a state that permits this transition.",
    "ERR_INVALID_ALERT_STATE": "The draining alert is not in a state that permits this transition.",
    "ERR_INVALID_CLAIM_STATE": "The victim claim is not in a state that permits this transition.",
    "ERR_INVALID_LISTING_STATE": "The reseller listing is not in a state that permits this transition.",
    "ERR_INVALID_PERIOD_STATE": "The liability period is not in a state that permits this transition.",
    "ERR_INVALID_HOLD_STATE": "The redemption hold is not in a state that permits this transition.",
    "ERR_LEDGER_EVENT_ALREADY_REVERSED": "That ledger event is not reversible.",
    "ERR_PERIOD_OVERLAP": "The requested accounting interval overlaps an existing period.",
    "ERR_DUPLICATE_LISTING": "An open listing already exists for this card and marketplace.",
    "ERR_PACKAGING_SEAL_BROKEN": "The tamper-evident packaging seal is broken.",
    "ERR_RACK_TAMPERED": "The card rack is not INTACT.",
    "ERR_STORE_FLOOR_SUSPENDED": "The retail floor is SUSPENDED.",
    "ERR_IDENTITY_VERIFICATION_REQUIRED": "Government identity capture is required before approval.",
    "ERR_EVIDENCE_INCOMPLETE": "Mandatory claim evidence is missing.",
    "ERR_ALERT_NOT_CONFIRMED": "The referenced draining alert is not CONFIRMED.",
    "ERR_CLAIM_WINDOW_EXPIRED": "The claim filing window has expired.",
    "ERR_BULK_QUANTITY_LIMIT_EXCEEDED": "The requested card quantity exceeds the bulk quantity limit.",
    "ERR_EVIDENCE_ROUND_LIMIT_EXCEEDED": "The evidence request round limit has been reached.",
    "ERR_INSUFFICIENT_BALANCE": "The card's available balance is insufficient.",
    "ERR_HOLD_CAPACITY_EXCEEDED": "The hold would exceed the card's aggregate hold capacity.",
    "ERR_REISSUE_LIMIT_EXCEEDED": "The gross reissue exceeds the reissue cap.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGE.get(error_id, error_id)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
