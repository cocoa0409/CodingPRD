"""Error catalogue (PRD §5 / SCAFFOLD §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and the role must be recognised.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorized for this operation.",
    "ERR_INVALID_REQUEST": "The request body is malformed or violates a declared field constraint.",
    "ERR_SELLER_NOT_FOUND": "The referenced seller account does not exist.",
    "ERR_FC_NOT_FOUND": "The referenced fulfillment center does not exist.",
    "ERR_LISTING_NOT_FOUND": "The referenced SKU listing does not exist.",
    "ERR_PLAN_NOT_FOUND": "The referenced inbound shipment plan does not exist.",
    "ERR_LOT_NOT_FOUND": "The referenced inventory lot does not exist.",
    "ERR_REMOVAL_ORDER_NOT_FOUND": "The referenced removal order does not exist.",
    "ERR_CLAIM_NOT_FOUND": "The referenced reimbursement claim does not exist.",
    "ERR_LINE_ITEM_NOT_FOUND": "A referenced shipment line item does not exist or does not belong to this plan.",
    "ERR_SELLER_SCOPE_VIOLATION": "The acting SellerOperator does not own the target resource.",
    "ERR_FC_SCOPE_VIOLATION": "The acting FcOperator is not the fulfillment center for this operation.",
    "ERR_STALE_SELLER_VERSION": "expected_seller_account_version does not match the seller account version.",
    "ERR_STALE_LOT_VERSION": "expected_inventory_lot_version does not match the inventory lot version.",
    "ERR_PLAN_NOT_DRAFT": "The plan is not in DRAFT.",
    "ERR_PLAN_NOT_CONFIRMED": "The plan is not in CONFIRMED.",
    "ERR_PLAN_NOT_RECEIVABLE": "The plan is not receivable.",
    "ERR_PLAN_NOT_CANCELLABLE": "The plan is not cancellable.",
    "ERR_REMOVAL_NOT_REQUESTED": "The removal order is not in REQUESTED.",
    "ERR_CLAIM_NOT_ACTIONABLE": "The claim is not in a status that permits this operation.",
    "ERR_LISTING_NOT_SUPPRESSED": "The listing is not SUPPRESSED.",
    "ERR_FC_RECEIVING_SUSPENDED": "The destination fulfillment center is not receiving.",
    "ERR_NO_ACTIVE_RESTOCK_QUOTA": "The seller has no ACTIVE restock quota period.",
    "ERR_LOT_NO_OPEN_DISCREPANCY": "The lot does not carry an open inbound discrepancy.",
    "ERR_SUPPRESSION_CONDITION_PERSISTS": "The listing still has no fulfillable units.",
    "ERR_REMOVAL_WINDOW_NOT_OPEN": "The removal execution window has not opened yet.",
    "ERR_PREP_REQUIREMENT_UNMET": "The destination prep profile requires polybagged units.",
    "ERR_LABEL_REQUIREMENT_UNMET": "The destination prep profile requires FNSKU labelling.",
    "ERR_APPOINTMENT_WINDOW_INVALID": "appointment_window_end must be strictly after appointment_window_start.",
    "ERR_APPOINTMENT_WINDOW_IN_PAST": "appointment_window_start must not be before the current logical clock instant.",
    "ERR_CLAIM_FILING_WINDOW_CLOSED": "The claim filing window has closed.",
    "ERR_CASE_PACK_VIOLATION": "The line item violates the case-pack rules.",
    "ERR_PLAN_HAS_NO_LINE_ITEMS": "The plan carries no line items.",
    "ERR_DUPLICATE_SKU": "A listing with this sku already exists for the seller.",
    "ERR_REMOVAL_WINDOW_CONFLICT": "The removal window collides with another requested removal on this lot.",
    "ERR_RESUBMISSION_LIMIT_REACHED": "The claim has exhausted its two resubmissions.",
    "ERR_LISTING_SELLER_MISMATCH": "The listing does not belong to the plan's seller.",
    "ERR_EVIDENCE_REFERENCE_MISSING": "The evidence document count is below the minimum for this claim type.",
    "ERR_INSUFFICIENT_POOL_UNITS": "The requested units exceed the available pool on the lot.",
    "ERR_REIMBURSEMENT_EXCEEDS_ELIGIBLE_UNITS": "The claimed units exceed the eligible pool on the lot.",
    "ERR_NO_FULFILLABLE_INVENTORY": "There is not enough fulfillable inventory to satisfy the order.",
    "ERR_FC_RECEIVING_CAPACITY_EXCEEDED": "The destination window capacity would be exceeded.",
    "ERR_RESTOCK_LIMIT_EXCEEDED": "The seller's restock limit cannot cover the plan's declared units.",
}
