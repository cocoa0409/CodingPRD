"""Error catalogue (PRD section 5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message if message is not None else DEFAULT_MESSAGE.get(
            error_id, error_id)


# error_id -> HTTP status
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,

    # not-found family
    "ERR_YARD_NOT_FOUND": 404,
    "ERR_LOADOUT_BAY_NOT_FOUND": 404,
    "ERR_CONSIGNOR_NOT_FOUND": 404,
    "ERR_CONSIGNMENT_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_CONDITION_REPORT_NOT_FOUND": 404,
    "ERR_REFURBISHMENT_ORDER_NOT_FOUND": 404,
    "ERR_AUCTION_NOT_FOUND": 404,
    "ERR_BIDDER_NOT_FOUND": 404,
    "ERR_REGISTRATION_NOT_FOUND": 404,
    "ERR_BID_NOT_FOUND": 404,
    "ERR_SALE_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_PAYMENT_NOT_FOUND": 404,
    "ERR_EXPORT_PACKET_NOT_FOUND": 404,
    "ERR_LOADOUT_SLOT_NOT_FOUND": 404,
    "ERR_SETTLEMENT_NOT_FOUND": 404,

    # optimistic concurrency
    "ERR_STALE_SALE_VERSION": 412,
    "ERR_STALE_INVOICE_VERSION": 412,

    # workflow gates
    "ERR_AUCTION_NOT_OPEN": 409,
    "ERR_REGISTRATION_NOT_APPROVED": 409,
    "ERR_CONSIGNMENT_NOT_CATALOGED": 409,
    "ERR_REFURBISHMENT_INCOMPLETE": 409,
    "ERR_TITLE_NOT_CLEAR": 409,
    "ERR_INVOICE_NOT_PAID": 409,
    "ERR_EXPORT_NOT_CLEARED": 409,
    "ERR_SETTLEMENT_INCOMPLETE": 409,

    # duplicate guards
    "ERR_DUPLICATE_CONDITION_REPORT": 409,
    "ERR_DUPLICATE_SETTLEMENT": 409,
    "ERR_DUPLICATE_REGISTRATION": 409,
    "ERR_DUPLICATE_SERIAL_NUMBER": 409,

    # eligibility
    "ERR_COUNTRY_EMBARGOED": 403,
    "ERR_BIDDER_SUSPENDED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,

    # cross-entity consistency
    "ERR_HOUR_METER_UNVERIFIED": 422,
    "ERR_BAY_YARD_MISMATCH": 409,
    "ERR_LOT_AUCTION_MISMATCH": 409,
    "ERR_DESTINATION_COUNTRY_MISMATCH": 422,
    "ERR_RESERVE_NOT_ALLOWED": 422,
    "ERR_UNRESERVED_POLICY_NOT_ACK": 422,

    # lap limits
    "ERR_MAX_REWORK_ROUNDS_EXCEEDED": 422,
    "ERR_MAX_COUNTER_ROUNDS_EXCEEDED": 422,
    "ERR_MAX_PACKET_REOPENS_EXCEEDED": 422,
    "ERR_COUNTER_PRICE_NOT_MONOTONIC": 422,

    # capacity / scheduling
    "ERR_BAY_INACTIVE": 409,
    "ERR_BAY_CAPACITY_EXCEEDED": 409,
    "ERR_AUCTION_WINDOW_CONFLICT": 409,
    "ERR_SLOT_OVERLAP": 409,
    "ERR_SLOT_OUTSIDE_DEADLINE": 422,
    "ERR_SLOT_NOT_IN_WINDOW": 409,

    # money
    "ERR_PAYMENT_NOT_OVERDUE": 409,
    "ERR_DEPOSIT_BELOW_MINIMUM": 422,
    "ERR_DEPOSIT_UNAVAILABLE": 422,
    "ERR_BID_CAP_EXCEEDED": 422,
    "ERR_BID_NOT_HIGHER": 422,
    "ERR_OVERPAYMENT": 422,
    "ERR_CURRENCY_MISMATCH": 422,
    "ERR_WAIVER_LIMIT_EXCEEDED": 422,

    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or invalid.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role may not call this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The acting principal does not own this resource.",
    "ERR_INVALID_REQUEST": "The request payload or query string is invalid.",
    "ERR_INVALID_STATE": "The resource is not in a state that permits this operation.",
}
