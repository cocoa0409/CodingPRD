"""Error catalogue for the Fastener Cold Heading & Thread Rolling API.

Every error_id / HTTP status pair below is taken verbatim from the PRD error
catalogue (PRD section 5).
"""

ERROR_HTTP = {
    # --- authentication / authorisation -----------------------------------
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- schema ------------------------------------------------------------
    "ERR_VALIDATION": 400,
    # --- existence ---------------------------------------------------------
    "ERR_PART_SPEC_NOT_FOUND": 404,
    "ERR_STEEL_HEAT_NOT_FOUND": 404,
    "ERR_WIRE_LOT_NOT_FOUND": 404,
    "ERR_HEADING_TOOL_NOT_FOUND": 404,
    "ERR_FURNACE_NOT_FOUND": 404,
    "ERR_PRODUCTION_LOT_NOT_FOUND": 404,
    "ERR_SECONDARY_OPERATION_NOT_FOUND": 404,
    "ERR_HEAT_TREAT_RUN_NOT_FOUND": 404,
    "ERR_PLATING_RUN_NOT_FOUND": 404,
    "ERR_LOT_TEST_NOT_FOUND": 404,
    "ERR_CERT_DOCUMENT_NOT_FOUND": 404,
    "ERR_PACK_UNIT_NOT_FOUND": 404,
    "ERR_NOT_FOUND": 404,
    # --- uniqueness --------------------------------------------------------
    "ERR_DUPLICATE_IDENTIFIER": 409,
    "ERR_DUPLICATE_MILL_CERT_SERIAL": 409,
    # --- optimistic concurrency -------------------------------------------
    "ERR_STALE_WIRE_LOT_VERSION": 412,
    "ERR_STALE_PRODUCTION_LOT_VERSION": 412,
    # --- disposition guards ------------------------------------------------
    "ERR_LOT_QUARANTINED": 409,
    "ERR_LOT_ON_HOLD": 409,
    # --- own-entity state --------------------------------------------------
    "ERR_INVALID_LOT_STATE": 409,
    "ERR_INVALID_TOOL_STATE": 409,
    "ERR_INVALID_HEAT_STATE": 409,
    "ERR_INVALID_WIRE_LOT_STATE": 409,
    "ERR_INVALID_SECONDARY_OP_STATE": 409,
    "ERR_INVALID_PROCESS_RUN_STATE": 409,
    "ERR_INVALID_CERT_STATE": 409,
    "ERR_INVALID_PACK_UNIT_STATE": 409,
    # --- cross entity state ------------------------------------------------
    "ERR_WIRE_LOT_NOT_RELEASED": 409,
    "ERR_STEEL_HEAT_NOT_VERIFIED": 409,
    "ERR_FURNACE_OCCUPIED": 409,
    "ERR_HEAT_TREAT_NOT_PASSED": 409,
    # --- process safety ----------------------------------------------------
    "ERR_HE_BAKE_WINDOW_MISSED": 422,
    "ERR_HE_BAKE_PARAMS_INVALID": 422,
    "ERR_BAKE_DURATION_NOT_ELAPSED": 409,
    "ERR_STRENGTH_CLASS_NOT_ACHIEVED": 422,
    "ERR_AEROSPACE_TOOL_UTILIZATION_EXCEEDED": 422,
    "ERR_THREAD_TIMING_VIOLATION": 422,
    "ERR_LUBRICATION_INSUFFICIENT": 422,
    "ERR_DRAW_REDUCTION_OUT_OF_RANGE": 422,
    "ERR_MILL_CERT_SERIAL_MISMATCH": 422,
    # --- referential -------------------------------------------------------
    "ERR_TEST_LOT_MISMATCH": 409,
    "ERR_TEST_NOT_ACCEPTED": 409,
    "ERR_CERT_LOT_MISMATCH": 409,
    "ERR_CERT_NOT_ISSUED": 409,
    "ERR_PART_SPEC_VERSION_DRIFT": 409,
    # --- temporal ----------------------------------------------------------
    "ERR_TOOL_WINDOW_CONFLICT": 409,
    "ERR_FURNACE_WINDOW_CONFLICT": 409,
    "ERR_OUTSIDE_RUN_WINDOW": 422,
    # --- business constraints ---------------------------------------------
    "ERR_GRADE_NOT_ALLOWED": 422,
    "ERR_OP_SEQUENCE_CONFLICT": 409,
    "ERR_SECONDARY_OPS_INCOMPLETE": 422,
    "ERR_BAKE_NOT_REQUIRED": 409,
    "ERR_PIECE_COUNT_INVALID": 422,
    "ERR_INSUFFICIENT_SAMPLE_PIECES": 422,
    "ERR_PACK_COUNT_OUT_OF_TOLERANCE": 422,
    "ERR_PACK_LABEL_INCOMPLETE": 422,
    "ERR_RISK_SCORE_TOO_HIGH": 422,
    # --- capacity ----------------------------------------------------------
    "ERR_WIRE_MASS_INSUFFICIENT": 422,
    "ERR_TOOL_LIFE_EXHAUSTED": 422,
    "ERR_FURNACE_CAPACITY_EXCEEDED": 422,
    # --- fallback ----------------------------------------------------------
    "ERR_INTERNAL": 500,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or invalid identity headers.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role may not perform this operation.",
    "ERR_SEGREGATION_OF_DUTIES": "The acting user may not sign their own test result.",
    "ERR_VALIDATION": "The request payload or query string is invalid.",
    "ERR_DUPLICATE_IDENTIFIER": "The supplied identifier is already in use.",
    "ERR_DUPLICATE_MILL_CERT_SERIAL": "The supplied mill certificate serial is already in use.",
    "ERR_LOT_QUARANTINED": "The production lot is quarantined.",
    "ERR_LOT_ON_HOLD": "The production lot is on hold.",
    "ERR_NOT_FOUND": "Resource not found.",
    "ERR_INTERNAL": "Internal server error.",
}


class ApiError(Exception):
    """A domain error that maps onto the PRD error envelope."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)
