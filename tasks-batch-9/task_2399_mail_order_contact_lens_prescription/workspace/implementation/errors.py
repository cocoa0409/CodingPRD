"""Error catalogue (PRD section 5 / SCAFFOLD errors)."""

ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": (401, "Caller identity headers are missing."),
    "ERR_UNAUTHORIZED": (403, "Role may not perform this operation."),
    "ERR_IDENTITY_MISMATCH": (403, "Entity-backed caller does not own the addressed resource."),
    "ERR_INVALID_REQUEST": (400, "Request body or query parameters are malformed."),
    "ERR_INVALID_STATE_TRANSITION": (409, "Requested transition is not declared for the current state."),
    "ERR_SEGREGATION_OF_DUTIES": (409, "The same user may not perform both steps of this two-person workflow."),
    "ERR_STALE_ORDER_VERSION": (412, "expected_order_version does not match the stored Order version."),
    "ERR_STALE_PRESCRIPTION_VERSION": (412, "expected_prescription_version does not match the stored Prescription version."),
    "ERR_INSURANCE_PLAN_NOT_FOUND": (404, "Insurance plan does not exist."),
    "ERR_PRODUCT_NOT_FOUND": (404, "Product does not exist."),
    "ERR_PRESCRIBER_NOT_FOUND": (404, "Prescriber does not exist."),
    "ERR_CUSTOMER_NOT_FOUND": (404, "Customer does not exist."),
    "ERR_PRESCRIPTION_NOT_FOUND": (404, "Prescription does not exist."),
    "ERR_VERIFICATION_REQUEST_NOT_FOUND": (404, "Verification request does not exist."),
    "ERR_ORDER_NOT_FOUND": (404, "Order does not exist."),
    "ERR_REORDER_HOLD_NOT_FOUND": (404, "Reorder hold does not exist."),
    "ERR_SCHEDULE_NOT_FOUND": (404, "Auto-reorder schedule does not exist."),
    "ERR_RETURN_REQUEST_NOT_FOUND": (404, "Return request does not exist."),
    "ERR_CLAIM_NOT_FOUND": (404, "Reimbursement claim does not exist."),
    "ERR_DISPUTE_NOT_FOUND": (404, "Prescriber dispute does not exist."),
    "ERR_DUPLICATE_EMAIL": (409, "A customer with this email already exists."),
    "ERR_DUPLICATE_LICENSE": (409, "A prescriber with this license number already exists in this state."),
    "ERR_EXPIRY_BEFORE_ISSUE": (400, "expiry_date must be strictly after issue_date."),
    "ERR_CAPTURE_MODE_REQUIRES_DOCUMENT": (400, "UPLOAD capture requires document_reference."),
    "ERR_CAPTURE_MODE_REQUIRES_PRESCRIBER": (400, "DOCTOR_LOOKUP capture requires prescriber_id."),
    "ERR_SELF_REPORT_REQUIRES_NAME": (400, "SELF_REPORT capture requires self_reported_prescriber_name."),
    "ERR_PRESCRIPTION_INTERVAL_OVERLAP": (
        409,
        "Prescription validity interval overlaps an existing prescription that it does not supersede.",
    ),
    "ERR_PRESCRIPTION_EXPIRED": (409, "Prescription is expired."),
    "ERR_PRESCRIPTION_NOT_VERIFIED": (409, "Prescription is not VERIFIED_ACTIVE."),
    "ERR_PRESCRIPTION_INVALIDATED": (409, "Prescription has been invalidated."),
    "ERR_PRESCRIBER_SUSPENDED": (409, "Prescriber is suspended and cannot be contacted."),
    "ERR_VERIFICATION_WINDOW_CLOSED": (409, "The passive verification window has already closed."),
    "ERR_PRESCRIBER_CONTACT_COOLDOWN": (
        429,
        "This prescriber was already contacted about this prescription inside the cooldown window.",
    ),
    "ERR_PRESCRIBER_REQUEST_CAPACITY": (409, "Prescriber already has the maximum number of pending verification requests."),
    "ERR_MAX_VERIFICATION_ROUNDS": (409, "The verification round cap has been reached."),
    "ERR_PARAMETER_DEVIATION_EXCEEDED": (422, "Parameter deviation index exceeds the maximum allowed for any substitution."),
    "ERR_CONSENT_REQUIRED": (422, "This substitution requires explicit patient consent."),
    "ERR_NO_EQUIVALENCE_MAPPING": (422, "No active lens equivalence maps these products."),
    "ERR_PRODUCT_INACTIVE": (409, "Product is inactive."),
    "ERR_OPEN_DISPUTE_BLOCKS_RELEASE": (409, "A dispute on this prescription is still open."),
    "ERR_HOLD_OPEN_BLOCKS_ACTION": (409, "An open reorder hold blocks this action."),
    "ERR_PLAN_RETIRED": (409, "Insurance plan is retired."),
    "ERR_PLAN_NOT_OUT_OF_NETWORK": (422, "Only out-of-network plans support reimbursement claims."),
    "ERR_ITEMIZED_RECEIPT_REQUIRED": (422, "This plan requires an itemized receipt reference on the order."),
    "ERR_CLAIM_WINDOW_CLOSED": (409, "The claim window for this order has closed."),
    "ERR_ALLOWANCE_EXHAUSTED": (409, "No plan-year allowance remains."),
    "ERR_BOX_AUTHORIZATION_EXCEEDED": (409, "Requested boxes exceed the prescription authorization."),
    "ERR_RETURN_QUANTITY_EXCEEDS_ORDER": (422, "Returned quantities exceed what the order shipped."),
    "ERR_REFUND_EXCEEDS_CAPTURE": (409, "Settlement would refund more than the order captured."),
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, status_code=None):
        super().__init__(error_id)
        default_status, default_message = ERROR_CATALOG.get(error_id, (400, "Request failed."))
        self.error_id = error_id
        self.message = message or default_message
        self.status_code = status_code or default_status
