"""Error catalogue (PRD section 5 / SCAFFOLD 1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or ERROR_MESSAGES.get(error_id, error_id)


# error_id -> HTTP status
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_POLICY_NOT_FOUND": 404,
    "ERR_STORE_NOT_FOUND": 404,
    "ERR_FRAME_NOT_FOUND": 404,
    "ERR_LENS_OPTION_NOT_FOUND": 404,
    "ERR_PRESCRIPTION_NOT_FOUND": 404,
    "ERR_KIT_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_LAB_ORDER_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_WARRANTY_CLAIM_NOT_FOUND": 404,
    "ERR_APPOINTMENT_NOT_FOUND": 404,
    "ERR_STALE_ORDER_VERSION": 412,
    "ERR_STALE_LAB_ORDER_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_PRESCRIPTION_NOT_VERIFIED": 409,
    "ERR_LAB_ORDER_NOT_DELIVERED": 409,
    "ERR_STORE_CLOSED": 409,
    "ERR_PD_OUT_OF_RANGE": 422,
    "ERR_LENS_INCOMPATIBLE_WITH_RX": 422,
    "ERR_COATING_INCOMPATIBLE": 422,
    "ERR_FRAME_DISCONTINUED": 422,
    "ERR_PRESCRIPTION_OWNER_MISMATCH": 422,
    "ERR_PRESCRIPTION_EXPIRED": 422,
    "ERR_WARRANTY_EXPIRED": 422,
    "ERR_KIT_EMPTY": 422,
    "ERR_KIT_SIZE_EXCEEDED": 422,
    "ERR_CUSTOMER_TRYON_BLOCKED": 403,
    "ERR_TRYON_WINDOW_CONFLICT": 409,
    "ERR_TRYON_STOCK_UNAVAILABLE": 409,
    "ERR_EXAM_SLOT_CONFLICT": 409,
    "ERR_BOPIS_STORE_REQUIRED": 422,
    "ERR_REMAKE_LIMIT_EXCEEDED": 409,
    "ERR_INSUFFICIENT_BENEFIT": 422,
    "ERR_INSUFFICIENT_FSA": 422,
    "ERR_ANNUAL_MAX_EXCEEDED": 422,
}

ERROR_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or invalid authentication headers.",
    "ERR_UNAUTHORIZED": "The acting role is not permitted to perform this operation.",
    "ERR_INVALID_REQUEST": "The request body failed schema validation.",
    "ERR_CUSTOMER_NOT_FOUND": "Customer not found.",
    "ERR_POLICY_NOT_FOUND": "Insurance policy not found.",
    "ERR_STORE_NOT_FOUND": "Store not found.",
    "ERR_FRAME_NOT_FOUND": "Frame not found.",
    "ERR_LENS_OPTION_NOT_FOUND": "Lens option not found.",
    "ERR_PRESCRIPTION_NOT_FOUND": "Prescription not found.",
    "ERR_KIT_NOT_FOUND": "Home try-on kit not found.",
    "ERR_ORDER_NOT_FOUND": "Order not found.",
    "ERR_LAB_ORDER_NOT_FOUND": "Lab order not found.",
    "ERR_CLAIM_NOT_FOUND": "Insurance claim not found.",
    "ERR_WARRANTY_CLAIM_NOT_FOUND": "Warranty claim not found.",
    "ERR_APPOINTMENT_NOT_FOUND": "Exam appointment not found.",
    "ERR_STALE_ORDER_VERSION": "expected_order_version does not match the order's current version.",
    "ERR_STALE_LAB_ORDER_VERSION": "expected_lab_order_version does not match the lab order's current version.",
    "ERR_INVALID_STATE": "The resource is not in a state from which this transition is declared.",
    "ERR_PRESCRIPTION_NOT_VERIFIED": "The referenced prescription is not VERIFIED.",
    "ERR_LAB_ORDER_NOT_DELIVERED": "The lab order has not been delivered.",
    "ERR_STORE_CLOSED": "The destination store is CLOSED.",
    "ERR_PD_OUT_OF_RANGE": "Pupillary distance is out of range.",
    "ERR_LENS_INCOMPATIBLE_WITH_RX": "The lens material is too weak for the prescription.",
    "ERR_COATING_INCOMPATIBLE": "The selected coatings are mutually incompatible.",
    "ERR_FRAME_DISCONTINUED": "The frame is DISCONTINUED and may not be ordered.",
    "ERR_PRESCRIPTION_OWNER_MISMATCH": "The prescription belongs to a different customer.",
    "ERR_PRESCRIPTION_EXPIRED": "The prescription has expired.",
    "ERR_WARRANTY_EXPIRED": "The warranty window has elapsed.",
    "ERR_KIT_EMPTY": "frame_ids must not be empty.",
    "ERR_KIT_SIZE_EXCEEDED": "A try-on kit may hold at most five distinct frames.",
    "ERR_CUSTOMER_TRYON_BLOCKED": "The customer's return risk score blocks new try-on kits.",
    "ERR_TRYON_WINDOW_CONFLICT": "The requested try-on window overlaps a live kit window.",
    "ERR_TRYON_STOCK_UNAVAILABLE": "No sample unit is available for a requested frame.",
    "ERR_EXAM_SLOT_CONFLICT": "The store's exam chairs are fully committed over the requested span.",
    "ERR_BOPIS_STORE_REQUIRED": "delivery_method and store_id disagree.",
    "ERR_REMAKE_LIMIT_EXCEEDED": "The lab order has already failed QC twice.",
    "ERR_INSUFFICIENT_BENEFIT": "The reservation would over-draw the policy's frame allowance.",
    "ERR_INSUFFICIENT_FSA": "fsa_amount_cents exceeds the customer's FSA balance.",
    "ERR_ANNUAL_MAX_EXCEEDED": "The policy has no remaining annual reimbursement headroom.",
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
