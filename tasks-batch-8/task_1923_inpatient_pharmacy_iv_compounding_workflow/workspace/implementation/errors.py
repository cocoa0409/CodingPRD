"""Error types and the error catalog for the Inpatient Pharmacy API.

Every error carries the exact error_id and HTTP status defined in the PRD
Section 5 error catalogue.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- auth (401/403) ---
def err_unauthenticated(msg="Missing or empty X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def err_role_mismatch(msg="Staff member missing, inactive, or staff_role does not match X-User-Role"):
    return ApiError("ERR_ROLE_MISMATCH", 403, msg)


def err_sod(msg="QA release/reject attempted by the batch compounder"):
    return ApiError("ERR_SOD_VIOLATION", 403, msg)


def err_not_order_prescriber(msg="Only the ordering prescriber may discontinue this order"):
    return ApiError("ERR_NOT_ORDER_PRESCRIBER", 403, msg)


# --- request / existence ---
def err_invalid_request(msg="Malformed request body"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_stale_version(msg="Expected version does not match the current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def err_order_terminal(msg="Order verification is DISCONTINUED/SUPERSEDED or fulfillment is ADMINISTERED"):
    return ApiError("ERR_ORDER_ALREADY_TERMINAL", 409, msg)


def err_invalid_state(msg="State-machine from-state does not allow the attempted transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_hood_overlap(msg="Hood session window overlaps an existing session on the same hood"):
    return ApiError("ERR_HOOD_OVERLAP", 409, msg)


def err_coverage_cap(msg="New coverage shift would create a three-way overlap in the zone"):
    return ApiError("ERR_COVERAGE_CAP_EXCEEDED", 409, msg)


def err_hood_session_not_active(msg="Hood session is not IN_USE"):
    return ApiError("ERR_HOOD_SESSION_NOT_ACTIVE", 409, msg)


def err_pocket_quarantined(msg="Pocket is QUARANTINED"):
    return ApiError("ERR_POCKET_QUARANTINED", 409, msg)


# --- 422 business ---
def err_allergy(msg="Ordered or substitute drug appears in the patient allergy list"):
    return ApiError("ERR_ALLERGY_CONFLICT", 422, msg)


def err_hd_cert(msg="Compounder lacks current hazardous-drug certification"):
    return ApiError("ERR_HD_CERTIFICATION_REQUIRED", 422, msg)


def err_hood_not_hd(msg="Hood is not rated for hazardous compounding"):
    return ApiError("ERR_HOOD_NOT_HD_RATED", 422, msg)


def err_witness_required(msg="Waste of a C_II drug requires witness_staff_id"):
    return ApiError("ERR_WITNESS_REQUIRED", 422, msg)


def err_witness_self(msg="Witness must differ from the recorder"):
    return ApiError("ERR_WITNESS_SELF_FORBIDDEN", 422, msg)


def err_invalid_quantity(msg="Quantity out of domain bounds"):
    return ApiError("ERR_INVALID_QUANTITY", 400, msg)


def err_pocket_capacity(msg="Restock would push on_hand_units above max_units"):
    return ApiError("ERR_POCKET_CAPACITY_EXCEEDED", 422, msg)


def err_insufficient_stock(msg="Units exceed pocket on_hand_units"):
    return ApiError("ERR_INSUFFICIENT_STOCK", 422, msg)


def err_drug_mismatch(msg="Order drug does not match pocket drug"):
    return ApiError("ERR_DRUG_MISMATCH", 422, msg)


def err_waste_tolerance(msg="Batch waste overage exceeds the size-tier tolerance"):
    return ApiError("ERR_WASTE_TOLERANCE_EXCEEDED", 422, msg)


def err_outside_window(msg="Logical clock is outside the session window"):
    return ApiError("ERR_HOOD_SESSION_OUTSIDE_WINDOW", 422, msg)


def err_bud_expired(msg="Preparation beyond-use expiry has been reached"):
    return ApiError("ERR_BUD_EXPIRED", 422, msg)


def err_protocol_expired(msg="Protocol activation attempted at or after expires_at"):
    return ApiError("ERR_PROTOCOL_EXPIRED", 422, msg)


def err_order_not_verified(msg="Order verification_status is not VERIFIED"):
    return ApiError("ERR_ORDER_NOT_VERIFIED", 422, msg)


def err_prep_not_qa(msg="No linked preparation in QA_PASSED"):
    return ApiError("ERR_PREPARATION_NOT_QA_PASSED", 422, msg)


def err_drug_discontinued(msg="Drug formulary status is not ACTIVE"):
    return ApiError("ERR_DRUG_DISCONTINUED", 422, msg)


def err_substitution_not_pending(msg="Order is not flagged substitution_pending"):
    return ApiError("ERR_SUBSTITUTION_NOT_PENDING", 422, msg)


def err_no_active_protocol(msg="No ACTIVE protocol matches the order's current drug"):
    return ApiError("ERR_NO_ACTIVE_PROTOCOL", 422, msg)


def err_no_eligible_substitute(msg="Substitute drug is not formulary-ACTIVE"):
    return ApiError("ERR_NO_ELIGIBLE_SUBSTITUTE", 422, msg)


def err_drug_not_in_shortage(msg="Shortage drug does not carry in_shortage"):
    return ApiError("ERR_DRUG_NOT_IN_SHORTAGE", 422, msg)
