class APIError(Exception):
    def __init__(self, error_id, message, status_code):
        self.error_id = error_id
        self.message = message
        self.status_code = status_code


ERROR_MAP = {
    "ERR_AUTH_HEADER_MISSING": (400, "Missing or invalid authentication headers."),
    "ERR_FORBIDDEN": (403, "You do not have permission to perform this action."),
    "ERR_NOT_SHOP_OWNER": (403, "You are not the owner of this shop."),
    "ERR_NOT_ORDER_OWNER": (403, "You are not the owner of this order."),
    "ERR_SHOP_NOT_FOUND": (404, "Shop not found."),
    "ERR_PRODUCT_NOT_FOUND": (404, "Product not found."),
    "ERR_PROMOTION_NOT_FOUND": (404, "Promotion not found."),
    "ERR_ORDER_NOT_FOUND": (404, "Order not found."),
    "ERR_REFUND_NOT_FOUND": (404, "Refund not found."),
    "ERR_SETTLEMENT_NOT_FOUND": (404, "Settlement not found."),
    "ERR_ORDER_ITEM_NOT_FOUND": (404, "Order item not found."),
    "ERR_SHOP_NOT_ACTIVE": (409, "Shop is not in ACTIVE state."),
    "ERR_SHOP_NOT_PENDING_REVIEW": (409, "Shop is not in PENDING_REVIEW state."),
    "ERR_PRODUCT_NOT_LISTED": (409, "Product is not in LISTED state."),
    "ERR_PRODUCT_NOT_DRAFT_OR_DELISTED": (409, "Product is not in DRAFT or DELISTED state."),
    "ERR_PRODUCT_NOT_LISTED_FOR_DELIST": (409, "Product is not in LISTED state for delisting."),
    "ERR_PROMOTION_NOT_DRAFT_OR_PAUSED": (409, "Promotion is not in DRAFT or PAUSED state."),
    "ERR_PROMOTION_NOT_ACTIVE": (409, "Promotion is not in ACTIVE state."),
    "ERR_ORDER_NOT_UNPAID": (409, "Order payment status is not UNPAID."),
    "ERR_ORDER_NOT_PAYING": (409, "Order payment status is not PAYING."),
    "ERR_ORDER_NOT_PAID": (409, "Order payment status is not PAID or PARTIAL_REFUND."),
    "ERR_ORDER_NOT_CONFIRMED": (409, "Order is not in CONFIRMED state."),
    "ERR_FULFILLMENT_NOT_PROCESSING": (409, "Fulfillment status is not PROCESSING."),
    "ERR_FULFILLMENT_NOT_SHIPPED": (409, "Fulfillment status is not SHIPPED."),
    "ERR_REFUND_NOT_REQUESTED": (409, "Refund is not in REQUESTED state."),
    "ERR_REFUND_NOT_APPROVED": (409, "Refund is not in APPROVED state."),
    "ERR_SETTLEMENT_NOT_DRAFT": (409, "Settlement is not in DRAFT state."),
    "ERR_SETTLEMENT_NOT_PENDING": (409, "Settlement is not in PENDING_APPROVAL state."),
    "ERR_SETTLEMENT_NOT_APPROVED": (409, "Settlement is not in APPROVED state."),
    "ERR_SETTLEMENT_NOT_DISPUTED_STATE": (409, "Settlement is not in DISPUTED state."),
    "ERR_INSUFFICIENT_INVENTORY": (409, "Product available count is less than the requested quantity."),
    "ERR_RESERVATION_EXPIRED": (409, "Order reservation has expired."),
    "ERR_PROMOTION_EXPIRED": (409, "Promotion end time has passed."),
    "ERR_CROSS_SHOP_ORDER": (400, "All products in an order must belong to the same shop."),
    "ERR_DUPLICATE_PROMOTION_PRIORITY": (409, "Another active promotion in this shop has the same priority."),
    "ERR_REFUND_EXCEEDS_REMAINING": (409, "Refund quantity exceeds remaining unrefunded quantity."),
    "ERR_REFUND_EXCEEDS_ORDER_TOTAL": (409, "Cumulative refunds exceed the order total amount."),
    "ERR_SETTLEMENT_PERIOD_OVERLAP": (409, "Settlement period overlaps with an existing non-terminal settlement."),
    "ERR_SETTLEMENT_ZERO_AMOUNT": (422, "Settlement net amount must be positive."),
    "ERR_SETTLEMENT_RECONCILIATION_MISMATCH": (422, "Settlement amounts do not reconcile."),
    "ERR_SHOP_HAS_PENDING_ORDERS": (409, "Shop has pending orders or unsettled balance."),
    "ERR_PRODUCT_HAS_RESERVATIONS": (409, "Product has outstanding reservations."),
    "ERR_INVALID_REQUEST": (400, "Invalid request."),
    "ERR_PROMOTION_USAGE_EXHAUSTED": (409, "Promotion has reached its maximum usage."),
    "ERR_STALE_DATA": (409, "Resource has been modified. Please retry with the latest version."),
}


def raise_error(error_id, message=None):
    status_code, default_message = ERROR_MAP.get(error_id, (400, "Unknown error."))
    raise APIError(error_id, message or default_message, status_code)
