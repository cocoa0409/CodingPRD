"""Error catalogue (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or unrecognized identity headers.",
    "ERR_FORBIDDEN_ROLE": "The acting role may not invoke this endpoint.",
    "ERR_ACCOUNT_SCOPE_VIOLATION": "The target resource belongs to a different pro account.",
    "ERR_SEGREGATION_OF_DUTIES": "The approving credit manager authored this negotiated round.",
    "ERR_INVALID_REQUEST": "The request body or query is malformed.",
    "ERR_STALE_VERSION": "The supplied expected version does not match the current version.",
    "ERR_DUPLICATE_STORE_STOCK": "A stock position already exists for this store and SKU.",
    "ERR_CREDIT_LINE_EXISTS": "This pro account already has a credit line.",
    "ERR_INVALID_STATE": "The requested transition is not available from the current state.",
    "ERR_ACCOUNT_ON_HOLD": "The pro account is on credit hold.",
    "ERR_CREDIT_LINE_FROZEN": "The account's credit line is frozen.",
    "ERR_CREDIT_LINE_NOT_FROZEN": "The credit line is already active.",
    "ERR_UTILIZATION_STILL_HIGH": "Credit utilization is still at or above the freeze threshold.",
    "ERR_ORDER_NOT_FULFILLED": "The order has not been fulfilled.",
    "ERR_ORDER_NOT_RESERVED": "The order is not in RESERVED.",
    "ERR_RESERVATIONS_NOT_ALLOCATED": "Every reservation of the order must be ALLOCATED.",
    "ERR_TRUCK_OUT_OF_SERVICE": "The assigned truck is out of service.",
    "ERR_QUOTE_TERM_ACTIVE": "The quote term has not run out yet.",
    "ERR_QUOTE_ROUND_LIMIT": "The negotiation round budget is spent.",
    "ERR_LIFT_GATE_UNAVAILABLE": "Lift-gate capability is unavailable.",
    "ERR_JOBSITE_ACCESS_UNSUPPORTED": "The truck does not support this jobsite access type.",
    "ERR_INVALID_DELIVERY_WINDOW": "window_end must be strictly after window_start.",
    "ERR_STAGE_WINDOW_TOO_LONG": "stage_hours exceeds the store's max_stage_hours.",
    "ERR_QUOTE_TERM_EXPIRED": "The quote's price-protection term does not cover this instant.",
    "ERR_RETURN_WINDOW_CLOSED": "The return window has closed.",
    "ERR_TRUCK_WINDOW_CONFLICT": "The buffered window conflicts with another appointment on this truck.",
    "ERR_WILL_CALL_CAPACITY_FULL": "The store's will-call bays are fully subscribed for this interval.",
    "ERR_DELIVERY_MODE_MISMATCH": "The order's delivery_mode does not match this scheduling channel.",
    "ERR_SKU_NOT_STOCKED": "The SKU has no stock position at the relevant store.",
    "ERR_NO_QUOTE_LINES": "The quote has no lines.",
    "ERR_QUOTE_ACCOUNT_MISMATCH": "The job quote belongs to a different pro account.",
    "ERR_QUOTE_NOT_ACCEPTED": "The referenced job quote is not ACCEPTED.",
    "ERR_PO_NUMBER_REQUIRED": "This account requires a non-empty po_number.",
    "ERR_JOB_NAME_REQUIRED": "This account requires a non-empty job_name.",
    "ERR_NO_VALID_TAX_CERTIFICATE": "No valid resale certificate for the fulfillment store's state.",
    "ERR_CERTIFICATE_STATE_MISMATCH": "The certificate's expires_on is not after the current clock date.",
    "ERR_NO_ORDER_LINES": "The order has no lines.",
    "ERR_INVALID_NEGOTIATED_PRICE": "A negotiated unit price is out of range.",
    "ERR_INCOMPLETE_COUNTER_OFFER": "The counter-offer must name every quote line.",
    "ERR_DISCOUNT_DEPTH_EXCEEDED": "The negotiated discount depth exceeds the approvable maximum.",
    "ERR_RETURN_QTY_EXCEEDS_FULFILLED": "A requested return quantity exceeds the available units.",
    "ERR_NO_SOURCING_CANDIDATES": "No candidate store carries the SKU with available units.",
    "ERR_INSUFFICIENT_JOB_LOT": "The sourcing waterfall cannot cover every line in full.",
    "ERR_JOB_LOT_SPLIT_NOT_ALLOWED": "A job-lot order cannot be split across stores.",
    "ERR_CREDIT_LIMIT_EXCEEDED": "The order exceeds the credit line's available headroom.",
    "ERR_PAYMENT_AMOUNT_MISMATCH": "amount_cents does not equal the amount owed.",
    "ERR_NO_REBATE_PAYABLE": "The accrual has no positive payable amount.",
}

NOT_FOUND = {
    "stores": "ERR_STORE_NOT_FOUND",
    "store_stocks": "ERR_STORE_STOCK_NOT_FOUND",
    "delivery_trucks": "ERR_DELIVERY_TRUCK_NOT_FOUND",
    "pro_accounts": "ERR_PRO_ACCOUNT_NOT_FOUND",
    "credit_lines": "ERR_CREDIT_LINE_NOT_FOUND",
    "tax_exempt_certificates": "ERR_TAX_EXEMPT_CERTIFICATE_NOT_FOUND",
    "job_quotes": "ERR_JOB_QUOTE_NOT_FOUND",
    "quote_lines": "ERR_QUOTE_LINE_NOT_FOUND",
    "pro_orders": "ERR_PRO_ORDER_NOT_FOUND",
    "order_lines": "ERR_ORDER_LINE_NOT_FOUND",
    "reservations": "ERR_RESERVATION_NOT_FOUND",
    "will_call_stagings": "ERR_WILL_CALL_STAGING_NOT_FOUND",
    "delivery_appointments": "ERR_DELIVERY_APPOINTMENT_NOT_FOUND",
    "rebate_accruals": "ERR_REBATE_ACCRUAL_NOT_FOUND",
    "return_requests": "ERR_RETURN_REQUEST_NOT_FOUND",
}


def invalid(message):
    return ApiError("ERR_INVALID_REQUEST", 400, message)
