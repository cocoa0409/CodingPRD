"""Error catalogue and the ApiError exception (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_CATALOG.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


# error_id -> http status
ERROR_CATALOG = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # existence
    "ERR_SELLER_NOT_FOUND": 404,
    "ERR_BUYER_NOT_FOUND": 404,
    "ERR_WAREHOUSE_NOT_FOUND": 404,
    "ERR_CARRIER_NOT_FOUND": 404,
    "ERR_BRAND_POLICY_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_MANIFEST_LINE_NOT_FOUND": 404,
    "ERR_LISTING_NOT_FOUND": 404,
    "ERR_NEGOTIATION_NOT_FOUND": 404,
    "ERR_OFFER_NOT_FOUND": 404,
    "ERR_SALE_ORDER_NOT_FOUND": 404,
    "ERR_APPOINTMENT_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # optimistic concurrency
    "ERR_STALE_LISTING_VERSION": 412,
    "ERR_STALE_NEGOTIATION_VERSION": 412,
    # state
    "ERR_LOT_STATE_INVALID": 409,
    "ERR_LISTING_STATE_INVALID": 409,
    "ERR_NEGOTIATION_STATE_INVALID": 409,
    "ERR_NOT_YOUR_TURN": 409,
    "ERR_ORDER_PAYMENT_STATE_INVALID": 409,
    "ERR_ORDER_LOGISTICS_STATE_INVALID": 409,
    "ERR_APPOINTMENT_STATE_INVALID": 409,
    "ERR_CLAIM_STATE_INVALID": 409,
    "ERR_BUYER_QUALIFICATION_STATE_INVALID": 409,
    # other-entity state
    "ERR_LOT_MANIFEST_NOT_APPROVED": 409,
    "ERR_SELLER_NOT_ACTIVE": 409,
    "ERR_BUYER_NOT_QUALIFIED": 409,
    "ERR_ORDER_NOT_PAID": 409,
    "ERR_PAYMENT_WINDOW_CLOSED": 409,
    "ERR_LINE_VOIDED": 409,
    # brand / geographic safety
    "ERR_CHANNEL_NOT_PERMITTED": 422,
    "ERR_DEBRANDING_ATTESTATION_REQUIRED": 422,
    "ERR_BUYER_STATE_PROHIBITED": 422,
    "ERR_SHILL_BIDDING_PROHIBITED": 422,
    # temporal
    "ERR_LISTING_WINDOW_NOT_OPEN": 422,
    "ERR_LISTING_WINDOW_CLOSED": 422,
    "ERR_AUCTION_NOT_CLOSABLE": 422,
    "ERR_OFFER_EXPIRED": 422,
    "ERR_PICKUP_DEADLINE_PASSED": 422,
    "ERR_APPOINTMENT_NOT_STARTED": 422,
    "ERR_CLAIM_WINDOW_CLOSED": 422,
    "ERR_RESALE_CERTIFICATE_EXPIRED": 422,
    "ERR_BRAND_EMBARGO_ACTIVE": 422,
    # capacity
    "ERR_DOCK_CAPACITY_EXHAUSTED": 422,
    "ERR_CARRIER_DAY_CAPACITY_FULL": 422,
    # structural
    "ERR_MANIFEST_EMPTY": 422,
    "ERR_LISTING_ALREADY_OPEN": 422,
    "ERR_DUPLICATE_NEGOTIATION": 422,
    "ERR_NEGOTIATION_ROUND_LIMIT": 422,
    "ERR_EVIDENCE_REQUEST_LIMIT": 422,
    "ERR_EVIDENCE_INSUFFICIENT": 422,
    "ERR_VERIFIED_UNITS_MISMATCH": 422,
    "ERR_CLAIMED_UNITS_EXCEED_LINE": 422,
    "ERR_LINE_NOT_ON_ORDER_LOT": 422,
    "ERR_WAREHOUSE_MISMATCH": 422,
    "ERR_BUSINESS_NOT_VERIFIED": 422,
    "ERR_DUPLICATE_TAX_ID": 422,
    "ERR_DUPLICATE_SCAC": 422,
    # money
    "ERR_RESERVE_BELOW_OPENING": 422,
    "ERR_BID_BELOW_MINIMUM": 422,
    "ERR_PROXY_MAX_BELOW_MINIMUM": 422,
    "ERR_FIXED_PRICE_MISMATCH": 422,
    "ERR_OFFER_BELOW_MINIMUM": 422,
    "ERR_CREDIT_LIMIT_EXCEEDED": 422,
    "ERR_PAYMENT_EXCEEDS_BALANCE": 422,
    # transport-level fallbacks
    "ERR_INTERNAL": 500,
}


DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or empty.",
    "ERR_ROLE_NOT_PERMITTED": "The caller's role may not perform this operation.",
    "ERR_NOT_RESOURCE_OWNER": "The caller does not own this resource.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this actor from deciding.",
    "ERR_INVALID_REQUEST": "The request payload is malformed or out of range.",
    "ERR_STALE_LISTING_VERSION": "The supplied listing version is stale.",
    "ERR_STALE_NEGOTIATION_VERSION": "The supplied negotiation version is stale.",
}


def api_error(error_id, message=None):
    return ApiError(error_id, message)
