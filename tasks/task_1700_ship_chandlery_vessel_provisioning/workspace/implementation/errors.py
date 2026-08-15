"""Error catalog and exception type.

Every error_id and HTTP status is taken verbatim from SCAFFOLD.yaml §1.6
and PRD §5.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- auth ---
def err_missing_context():
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                    "X-User-ID or X-User-Role header missing/empty")


def err_insufficient_permissions():
    return ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403,
                    "Role not permitted for endpoint, or entity-backed ownership check failed")


# --- request shape ---
def err_invalid_request(msg="Request body not well-formed"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


# --- not found ---
def err_vessel_call_not_found():
    return ApiError("ERR_VESSEL_CALL_NOT_FOUND", 404, "VesselCall id not found")


def err_agent_not_found():
    return ApiError("ERR_AGENT_NOT_FOUND", 404, "ShipAgent id not found")


def err_catalog_item_not_found():
    return ApiError("ERR_CATALOG_ITEM_NOT_FOUND", 404, "CatalogItem id not found")


def err_stock_lot_not_found():
    return ApiError("ERR_STOCK_LOT_NOT_FOUND", 404, "StockLot id not found")


def err_requisition_not_found():
    return ApiError("ERR_REQUISITION_NOT_FOUND", 404, "Requisition id not found")


def err_quotation_not_found():
    return ApiError("ERR_QUOTATION_NOT_FOUND", 404, "Quotation id not found")


def err_order_not_found():
    return ApiError("ERR_ORDER_NOT_FOUND", 404, "Order id not found")


def err_delivery_not_found():
    return ApiError("ERR_DELIVERY_NOT_FOUND", 404, "Delivery id not found")


def err_invoice_not_found():
    return ApiError("ERR_INVOICE_NOT_FOUND", 404, "Invoice id not found")


def err_complaint_not_found():
    return ApiError("ERR_COMPLAINT_NOT_FOUND", 404, "QualityComplaint id not found")


def err_credit_note_not_found():
    return ApiError("ERR_CREDIT_NOTE_NOT_FOUND", 404, "CreditNote id not found")


# --- state ---
def err_vessel_call_not_arrivable():
    return ApiError("ERR_VESSEL_CALL_NOT_ARRIVABLE", 409, "arrive requires status == SCHEDULED")


def err_vessel_call_not_in_port():
    return ApiError("ERR_VESSEL_CALL_NOT_IN_PORT", 409,
                    "Operation requires the vessel call to be IN_PORT (or SCHEDULED/IN_PORT)")


def err_vessel_call_not_cancellable():
    return ApiError("ERR_VESSEL_CALL_NOT_CANCELLABLE", 409, "Vessel call cancel requires status == SCHEDULED")


def err_customs_state_invalid():
    return ApiError("ERR_CUSTOMS_STATE_INVALID", 409,
                    "Customs decision not admissible from current customs_clearance_status")


def err_requisition_not_submittable():
    return ApiError("ERR_REQUISITION_NOT_SUBMITTABLE", 409, "submit requires requisition DRAFT")


def err_requisition_not_recallable():
    return ApiError("ERR_REQUISITION_NOT_RECALLABLE", 409, "recall requires requisition SUBMITTED")


def err_requisition_has_live_quotation():
    return ApiError("ERR_REQUISITION_HAS_LIVE_QUOTATION", 409,
                    "recall blocked while a SENT quotation exists on the requisition")


def err_requisition_not_open_for_quotes():
    return ApiError("ERR_REQUISITION_NOT_OPEN_FOR_QUOTES", 409,
                    "quotation create requires requisition SUBMITTED or QUOTED")


def err_quotation_not_sendable():
    return ApiError("ERR_QUOTATION_NOT_SENDABLE", 409, "send requires quotation DRAFT")


def err_quotation_not_revisable():
    return ApiError("ERR_QUOTATION_NOT_REVISABLE", 409, "revise requires quotation SENT")


def err_quotation_not_acceptable():
    return ApiError("ERR_QUOTATION_NOT_ACCEPTABLE", 409, "accept requires quotation SENT")


def err_quotation_not_withdrawable():
    return ApiError("ERR_QUOTATION_NOT_WITHDRAWABLE", 409, "withdraw requires quotation DRAFT or SENT")


def err_quotation_expired():
    return ApiError("ERR_QUOTATION_EXPIRED", 409, "now > valid_until at send/revise/accept")


def err_order_not_cancellable():
    return ApiError("ERR_ORDER_NOT_CANCELLABLE", 409,
                    "order cancel requires fulfillment OPEN and payment UNINVOICED or INVOICED with zero payments")


def err_order_not_invoicable():
    return ApiError("ERR_ORDER_NOT_INVOICABLE", 409,
                    "invoice issue requires payment_status == UNINVOICED and fulfillment DELIVERED or (PARTIALLY_DELIVERED and vessel DEPARTED)")


def err_delivery_not_dispatchable():
    return ApiError("ERR_DELIVERY_NOT_DISPATCHABLE", 409, "dispatch requires delivery SCHEDULED")


def err_delivery_not_confirmable():
    return ApiError("ERR_DELIVERY_NOT_CONFIRMABLE", 409, "confirm requires delivery OUT_FOR_DELIVERY")


def err_invoice_not_payable():
    return ApiError("ERR_INVOICE_NOT_PAYABLE", 409, "payment requires invoice ISSUED or PARTIALLY_PAID")


def err_complaint_not_reviewable():
    return ApiError("ERR_COMPLAINT_NOT_REVIEWABLE", 409, "accept/reject requires complaint SUBMITTED")


def err_complaint_not_reopenable():
    return ApiError("ERR_COMPLAINT_NOT_REOPENABLE", 409, "reopen requires complaint REJECTED")


def err_credit_note_not_revocable():
    return ApiError("ERR_CREDIT_NOTE_NOT_REVOCABLE", 409, "revoke requires credit note APPLIED")


# --- concurrency ---
def err_stale_version():
    return ApiError("ERR_STALE_VERSION", 412,
                    "expected_<parent>_version does not match the parent entity's current version")


# --- business safety ---
def err_customs_clearance_required():
    return ApiError("ERR_CUSTOMS_CLEARANCE_REQUIRED", 403,
                    "Delivery contains bonded_eligible items but the vessel call's customs_clearance_status != CLEARED")


def err_bonded_item_not_eligible():
    return ApiError("ERR_BONDED_ITEM_NOT_ELIGIBLE", 422,
                    "Substitution into a bonded_eligible item from a non-bonded_eligible original (or reverse)")


def err_segregation_of_duties():
    return ApiError("ERR_SEGREGATION_OF_DUTIES_VIOLATION", 403,
                    "Same X-User-ID on both sides of a segregated pair")


# --- business temporal ---
def err_delivery_window_inverted():
    return ApiError("ERR_DELIVERY_WINDOW_INVERTED", 400, "window_end <= window_start")


def err_window_outside_port_stay():
    return ApiError("ERR_WINDOW_OUTSIDE_PORT_STAY", 409,
                    "Delivery window not contained in [eta, etd]")


# --- business constraint ---
def err_invalid_qty(msg="Quantity violates its floor"):
    return ApiError("ERR_INVALID_QTY", 400, msg)


def err_qty_exceeds_remaining():
    return ApiError("ERR_QTY_EXCEEDS_REMAINING", 409,
                    "Confirmed qty exceeds delivery plan or order remaining; or rejected qty exceeds delivered qty")


def err_substitution_not_allowed():
    return ApiError("ERR_SUBSTITUTION_NOT_ALLOWED", 422,
                    "Substitution when requisition line disallows it, or category/cold-chain mismatch, or uncovered requisition line")


def err_substitution_price_cap_exceeded():
    return ApiError("ERR_SUBSTITUTION_PRICE_CAP_EXCEEDED", 422,
                    "Substitute unit_price_cents > round_half_up(original base_price_cents * 115/100)")


def err_stock_insufficient():
    return ApiError("ERR_STOCK_INSUFFICIENT", 409,
                    "Reservation waterfall cannot fully allocate every order line")


def err_cold_chain_capacity_exceeded():
    return ApiError("ERR_COLD_CHAIN_CAPACITY_EXCEEDED", 409,
                    "Overlapping cold reservations on a COLD_STORE lot would exceed capacity_qty")


# --- business referential ---
def err_duplicate_sku():
    return ApiError("ERR_DUPLICATE_SKU", 409,
                    "CatalogItem.sku already exists; or StockLot.lot_code already exists for the same catalog item")


def err_currency_mismatch():
    return ApiError("ERR_CURRENCY_MISMATCH", 422,
                    "Payment currency != invoice settlement currency and no fx_rate_to_invoice_currency provided")


def err_invalid_fx_rate():
    return ApiError("ERR_INVALID_FX_RATE", 400, "FX rate missing where required, or <= 0")


def err_no_creditable_invoice():
    return ApiError("ERR_NO_CREDITABLE_INVOICE", 409,
                    "Complaint accept finds no invoice in ISSUED|PARTIALLY_PAID for the order, or computed credit amount <= 0")


# --- business fiscal ---
def err_credit_limit_exceeded():
    return ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 402,
                    "order_total_cents > credit_limit_cents - committed_exposure_cents at accept")


def err_payment_overpayment():
    return ApiError("ERR_PAYMENT_OVERPAYMENT", 422,
                    "Converted payment sum exceeds outstanding + 50 cents")
