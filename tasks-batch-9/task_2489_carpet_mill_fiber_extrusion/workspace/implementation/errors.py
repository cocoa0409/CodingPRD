"""Error catalogue for the carpet-mill fiber-extrusion API.

Every entry maps an ``error_id`` to the HTTP status declared in PRD.md section 5.
"""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_STATUS = {
    # --- authentication / authorization / scope ---------------------------
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_ACCOUNT_SCOPE_VIOLATION": 403,
    # --- existence --------------------------------------------------------
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_POLYMER_LOT_NOT_FOUND": 404,
    "ERR_RECLAMATION_BATCH_NOT_FOUND": 404,
    "ERR_FIBER_BATCH_NOT_FOUND": 404,
    "ERR_STYLE_NOT_FOUND": 404,
    "ERR_MACHINE_NOT_FOUND": 404,
    "ERR_VESSEL_NOT_FOUND": 404,
    "ERR_PRODUCTION_RUN_NOT_FOUND": 404,
    "ERR_DYE_LOT_NOT_FOUND": 404,
    "ERR_ROLL_GOOD_NOT_FOUND": 404,
    "ERR_PRODUCT_TEST_NOT_FOUND": 404,
    "ERR_CERTIFICATION_NOT_FOUND": 404,
    "ERR_CUT_ORDER_NOT_FOUND": 404,
    "ERR_CUT_ALLOCATION_NOT_FOUND": 404,
    # --- shape ------------------------------------------------------------
    "ERR_INVALID_REQUEST": 400,
    # --- uniqueness -------------------------------------------------------
    "ERR_DUPLICATE_CODE": 409,
    # --- state legality ---------------------------------------------------
    "ERR_INVALID_STATE": 409,
    "ERR_FIBER_BATCH_NOT_RELEASED": 409,
    "ERR_RUN_NOT_BACKED": 409,
    "ERR_DYE_LOT_NOT_APPROVED": 409,
    "ERR_ROLL_ALREADY_DEPLETED": 409,
    "ERR_STYLE_NOT_ACTIVE": 409,
    "ERR_STYLE_NOT_ORDERABLE": 409,
    "ERR_STYLE_RUNOUT_NO_CUSTOM": 409,
    "ERR_MACHINE_UNAVAILABLE": 409,
    "ERR_VESSEL_UNAVAILABLE": 409,
    "ERR_REDYE_LIMIT_REACHED": 409,
    "ERR_RECOAT_LIMIT_REACHED": 409,
    "ERR_ACCOUNT_CREDIT_HOLD": 409,
    "ERR_ACCOUNT_CLOSED": 409,
    "ERR_ACCOUNT_HAS_OPEN_ORDERS": 409,
    # --- optimistic concurrency ------------------------------------------
    "ERR_STALE_DYE_LOT_VERSION": 412,
    "ERR_STALE_ROLL_GOOD_VERSION": 412,
    # --- compliance -------------------------------------------------------
    "ERR_FLAMMABILITY_CERT_REQUIRED": 422,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_CERT_EVIDENCE_MISSING": 422,
    "ERR_RECYCLED_CONTENT_INSUFFICIENT": 422,
    # --- extrusion --------------------------------------------------------
    "ERR_MELT_FLOW_OUT_OF_RANGE": 422,
    "ERR_POLYMER_BLEND_INCOMPATIBLE": 422,
    "ERR_POLYMER_MASS_UNAVAILABLE": 422,
    "ERR_DENIER_OUT_OF_TOLERANCE": 422,
    # --- tufting setup ----------------------------------------------------
    "ERR_GAUGE_MISMATCH": 422,
    "ERR_MACHINE_GAUGE_INCOMPATIBLE": 422,
    "ERR_PILE_HEIGHT_OUT_OF_RANGE": 422,
    "ERR_PILE_HEIGHT_SPEC_DEVIATION": 422,
    "ERR_PATTERN_REPEAT_MISMATCH": 422,
    "ERR_FACE_WEIGHT_OUT_OF_TOLERANCE": 422,
    # --- dye routing ------------------------------------------------------
    "ERR_DYE_METHOD_COLOR_MISMATCH": 422,
    "ERR_DYE_METHOD_MISMATCH": 422,
    "ERR_SOLUTION_DYED_NO_DYE_LOT": 422,
    "ERR_DYE_LOT_REQUIRED": 422,
    "ERR_SHADE_BAND_NOT_APPROVABLE": 422,
    "ERR_SHADE_BAND_NOT_REDYEABLE": 422,
    "ERR_SHADE_BAND_MISMATCH": 422,
    # --- scheduling windows ----------------------------------------------
    "ERR_MACHINE_WINDOW_CONFLICT": 409,
    "ERR_VESSEL_CAPACITY_EXCEEDED": 409,
    "ERR_RUN_WINDOW_NOT_OPEN": 409,
    "ERR_DYE_WINDOW_NOT_OPEN": 409,
    # --- reclamation ------------------------------------------------------
    "ERR_RECLAIM_CONTAMINATION_EXCEEDED": 422,
    "ERR_ROLL_NOT_RECLAIMABLE": 422,
    # --- allocation -------------------------------------------------------
    "ERR_DYE_LOT_EXHAUSTED": 409,
    "ERR_ROLL_NOT_ALLOCATABLE": 422,
    "ERR_ROLL_YARDAGE_INSUFFICIENT": 422,
    "ERR_NO_ELIGIBLE_ROLL_GOODS": 409,
    "ERR_INSUFFICIENT_YARDAGE": 422,
    "ERR_CREDIT_LIMIT_EXCEEDED": 422,
    # --- transport-level fallbacks (not part of the catalogue) ------------
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or invalid",
    "ERR_UNAUTHORIZED": "The acting role may not perform this operation",
    "ERR_ACCOUNT_SCOPE_VIOLATION": "The acting dealer may only act on its own account",
    "ERR_INVALID_REQUEST": "The request body or query string is malformed",
    "ERR_DUPLICATE_CODE": "A record with that natural key already exists",
    "ERR_INVALID_STATE": "The target record is not in a state that admits this transition",
    "ERR_NOT_FOUND": "The requested resource does not exist",
    "ERR_METHOD_NOT_ALLOWED": "That method is not allowed on this path",
}
