"""Error classes and error ID constants per the PRD error catalogue."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- Auth (401 / 403) ---
def err_unauthenticated(msg="Missing or invalid X-User-Role or X-User-ID header"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_unauthorized_role(msg="Role not permitted on this endpoint"):
    return ApiError("ERR_UNAUTHORIZED_ROLE", 403, msg)


def err_segregation(msg="Segregation of duties violation"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


def err_not_payment_recorder(msg="Only the recording treasurer may void this payment"):
    return ApiError("ERR_NOT_PAYMENT_RECORDER", 403, msg)


# --- Validation (400) ---
def err_validation(msg="Request body schema violation"):
    return ApiError("ERR_VALIDATION", 400, msg)


# --- Not found (404) ---
def err_campaign_not_found(msg="Campaign not found"):
    return ApiError("ERR_CAMPAIGN_NOT_FOUND", 404, msg)


def err_group_not_found(msg="Group not found"):
    return ApiError("ERR_GROUP_NOT_FOUND", 404, msg)


def err_product_not_found(msg="Product not found"):
    return ApiError("ERR_PRODUCT_NOT_FOUND", 404, msg)


def err_prize_not_found(msg="Prize not found"):
    return ApiError("ERR_PRIZE_NOT_FOUND", 404, msg)


def err_seller_not_found(msg="Seller not found"):
    return ApiError("ERR_SELLER_NOT_FOUND", 404, msg)


def err_order_not_found(msg="Order not found"):
    return ApiError("ERR_ORDER_NOT_FOUND", 404, msg)


def err_payment_not_found(msg="Payment not found"):
    return ApiError("ERR_PAYMENT_NOT_FOUND", 404, msg)


def err_supplier_order_not_found(msg="Supplier order not found"):
    return ApiError("ERR_SUPPLIER_ORDER_NOT_FOUND", 404, msg)


def err_distribution_event_not_found(msg="Distribution event not found"):
    return ApiError("ERR_DISTRIBUTION_EVENT_NOT_FOUND", 404, msg)


def err_sort_ticket_not_found(msg="Sort ticket not found"):
    return ApiError("ERR_SORT_TICKET_NOT_FOUND", 404, msg)


def err_claim_not_found(msg="Reconciliation claim not found"):
    return ApiError("ERR_CLAIM_NOT_FOUND", 404, msg)


def err_return_not_found(msg="Return request not found"):
    return ApiError("ERR_RETURN_NOT_FOUND", 404, msg)


def err_appointment_not_found(msg="Pickup appointment not found"):
    return ApiError("ERR_APPOINTMENT_NOT_FOUND", 404, msg)


def err_prize_award_not_found(msg="Prize award not found"):
    return ApiError("ERR_PRIZE_AWARD_NOT_FOUND", 404, msg)


def err_order_line_not_found(msg="Order line not found"):
    return ApiError("ERR_ORDER_LINE_NOT_FOUND", 404, msg)


# --- Idempotency / OCC (409 / 412) ---
def err_idempotency_conflict(msg="idempotency_key replayed with a different payload"):
    return ApiError("ERR_IDEMPOTENCY_CONFLICT", 409, msg)


def err_stale_version(msg="Stale version: the resource has been modified since last read"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


# --- State (409) ---
def err_invalid_state(msg="Transition not permitted from current state"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_campaign_not_ready(msg="Campaign not ready: needs at least one ACTIVE product and one student group"):
    return ApiError("ERR_CAMPAIGN_NOT_READY", 409, msg)


def err_campaign_not_open(msg="Campaign is not OPEN"):
    return ApiError("ERR_CAMPAIGN_NOT_OPEN", 409, msg)


def err_seller_suspended(msg="Seller is SUSPENDED"):
    return ApiError("ERR_SELLER_SUSPENDED", 409, msg)


def err_product_not_orderable(msg="Product is not orderable (DISCONTINUED)"):
    return ApiError("ERR_PRODUCT_NOT_ORDERABLE", 409, msg)


def err_duplicate_sku(msg="Product SKU already exists within the campaign"):
    return ApiError("ERR_DUPLICATE_SKU", 409, msg)


def err_duplicate_group_name(msg="Group name already exists within the campaign"):
    return ApiError("ERR_DUPLICATE_GROUP_NAME", 409, msg)


def err_duplicate_seller_name(msg="Seller display_name already exists within the group"):
    return ApiError("ERR_DUPLICATE_SELLER_NAME", 409, msg)


def err_order_has_cleared_payments(msg="Order has cleared payments"):
    return ApiError("ERR_ORDER_HAS_CLEARED_PAYMENTS", 409, msg)


def err_venue_overlap(msg="Another SCHEDULED event for the same campaign and venue overlaps this window"):
    return ApiError("ERR_VENUE_OVERLAP", 409, msg)


def err_campaign_has_active_supplier_order(msg="A non-cancelled, non-delivered supplier order already exists"):
    return ApiError("ERR_CAMPAIGN_HAS_ACTIVE_SUPPLIER_ORDER", 409, msg)


def err_appeal_limit_exceeded(msg="Only a root claim may be appealed; one appeal per chain"):
    return ApiError("ERR_APPEAL_LIMIT_EXCEEDED", 409, msg)


def err_sort_tickets_already_generated(msg="Sort tickets already exist for the campaign"):
    return ApiError("ERR_SORT_TICKETS_ALREADY_GENERATED", 409, msg)


def err_unverified_sort_tickets(msg="Sort tickets remain PENDING"):
    return ApiError("ERR_UNVERIFIED_SORT_TICKETS", 409, msg)


def err_open_claims_or_returns(msg="Open claims, returns, or appointments block this transition"):
    return ApiError("ERR_OPEN_CLAIMS_OR_RETURNS", 409, msg)


def err_campaign_cancel_blocked(msg="Campaign cancel blocked: cleared payments exist"):
    return ApiError("ERR_CAMPAIGN_CANCEL_BLOCKED", 409, msg)


# --- Temporal (422) ---
def err_outside_order_window(msg="Outside the order window"):
    return ApiError("ERR_OUTSIDE_ORDER_WINDOW", 422, msg)


def err_order_window_not_yet_closed(msg="Order window has not yet closed"):
    return ApiError("ERR_ORDER_WINDOW_NOT_YET_CLOSED", 422, msg)


def err_return_window_expired(msg="Return window has expired"):
    return ApiError("ERR_RETURN_WINDOW_EXPIRED", 422, msg)


def err_return_window_not_elapsed(msg="Return window has not fully elapsed"):
    return ApiError("ERR_RETURN_WINDOW_NOT_ELAPSED", 422, msg)


def err_event_not_started(msg="Event window has not started"):
    return ApiError("ERR_EVENT_NOT_STARTED", 422, msg)


def err_appointment_window_outside(msg="Slot not contained in the event window"):
    return ApiError("ERR_APPOINTMENT_WINDOW_OUTSIDE", 422, msg)


# --- Business constraints (422 unless noted) ---
def err_quantity_invalid(msg="Quantity out of allowed range"):
    return ApiError("ERR_QUANTITY_INVALID", 422, msg)


def err_overpayment(msg="Payment would push recorded+cleared coverage above order total"):
    return ApiError("ERR_OVERPAYMENT", 422, msg)


def err_refund_exceeds_cleared(msg="Refund exceeds remaining un-refunded cleared value"):
    return ApiError("ERR_REFUND_EXCEEDS_CLEARED", 422, msg)


def err_payment_method_not_bounceable(msg="Only CHECK payments may bounce"):
    return ApiError("ERR_PAYMENT_METHOD_NOT_BOUNCEABLE", 422, msg)


def err_slot_capacity_exceeded(msg="Booking would exceed slot capacity at some instant"):
    return ApiError("ERR_SLOT_CAPACITY_EXCEEDED", 422, msg)


def err_cross_campaign_reference(msg="Referenced entities belong to different campaigns"):
    return ApiError("ERR_CROSS_CAMPAIGN_REFERENCE", 422, msg)


def err_order_line_mismatch(msg="order_line_id does not belong to order_id"):
    return ApiError("ERR_ORDER_LINE_MISMATCH", 422, msg)


def err_no_submitted_orders(msg="Supplier order has zero aggregated units"):
    return ApiError("ERR_NO_SUBMITTED_ORDERS", 422, msg)


def err_insufficient_surplus(msg="Insufficient surplus units for replacement"):
    return ApiError("ERR_INSUFFICIENT_SURPLUS", 422, msg)


def err_claim_qty_exceeds_available(msg="Claim quantity exceeds line availability"):
    return ApiError("ERR_CLAIM_QTY_EXCEEDS_AVAILABLE", 422, msg)


def err_return_qty_exceeds_available(msg="Return quantity exceeds line availability"):
    return ApiError("ERR_RETURN_QTY_EXCEEDS_AVAILABLE", 422, msg)


def err_product_not_returnable(msg="Product is not returnable"):
    return ApiError("ERR_PRODUCT_NOT_RETURNABLE", 422, msg)


def err_per_seller_limit_exceeded(msg="Cumulative units would exceed product per_seller_limit"):
    return ApiError("ERR_PER_SELLER_LIMIT_EXCEEDED", 422, msg)
