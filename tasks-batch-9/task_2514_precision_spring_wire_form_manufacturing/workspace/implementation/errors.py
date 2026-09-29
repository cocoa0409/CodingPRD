"""Error catalog and the ApiError exception.

Every error_id / HTTP status pair here is taken verbatim from PRD section 5
(Error Codes) and SCAFFOLD.yaml section 1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_STATUS = {
    # ---- authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_PROGRAM_OWNERSHIP_MISMATCH": 403,
    # ---- request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    # ---- existence
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_MATERIAL_SPEC_NOT_FOUND": 404,
    "ERR_DESIGN_NOT_FOUND": 404,
    "ERR_CHARACTERISTIC_NOT_FOUND": 404,
    "ERR_TOOLING_NOT_FOUND": 404,
    "ERR_WIRE_LOT_NOT_FOUND": 404,
    "ERR_MACHINE_NOT_FOUND": 404,
    "ERR_SETUP_NOT_FOUND": 404,
    "ERR_RUN_NOT_FOUND": 404,
    "ERR_OVEN_NOT_FOUND": 404,
    "ERR_BATCH_NOT_FOUND": 404,
    "ERR_SUBMISSION_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    # ---- optimistic concurrency
    "ERR_STALE_DESIGN_VERSION": 412,
    "ERR_STALE_MACHINE_VERSION": 412,
    "ERR_STALE_PROGRAM_VERSION": 412,
    # ---- state
    "ERR_DESIGN_INVALID_STATE": 409,
    "ERR_DESIGN_LOCKED": 409,
    "ERR_RUN_NOT_COMPLETE": 409,
    "ERR_RUN_ON_SPC_HOLD": 409,
    "ERR_RUN_INVALID_STATE": 409,
    "ERR_SETUP_NOT_ACTIVE": 409,
    "ERR_SETUP_INVALID_STATE": 409,
    "ERR_MACHINE_NOT_IDLE": 409,
    "ERR_WIRE_LOT_ALREADY_DECIDED": 409,
    "ERR_FAI_ALREADY_DISPOSITIONED": 409,
    "ERR_RUN_NOT_ON_HOLD": 409,
    "ERR_SUBMISSION_INVALID_STATE": 409,
    "ERR_LOT_INVALID_STATE": 409,
    "ERR_BATCH_INVALID_STATE": 409,
    "ERR_QUOTE_FROZEN": 409,
    # ---- business safety
    "ERR_CORROSION_REQUIREMENT_UNMET": 422,
    "ERR_BIOCOMPATIBILITY_REQUIRED": 422,
    "ERR_SELF_REVIEW_FORBIDDEN": 409,
    "ERR_FATIGUE_MARGIN_BELOW_FLOOR": 422,
    "ERR_SELF_DISPOSITION_FORBIDDEN": 409,
    "ERR_WIRE_LOT_NOT_CERTIFIED": 422,
    "ERR_PPAP_NOT_APPROVED": 422,
    "ERR_HEAT_TREAT_INCOMPLETE": 422,
    "ERR_PPK_BELOW_PROGRAM_FLOOR": 422,
    "ERR_PROGRAM_POSTURE_BLOCKED": 409,
    "ERR_PACKAGING_NOT_PERMITTED": 422,
    "ERR_TANGLE_RISK_PACKAGING": 422,
    # ---- referential
    "ERR_SETUP_DESIGN_MISMATCH": 422,
    "ERR_MATERIAL_MISMATCH": 422,
    "ERR_TOOLING_DESIGN_MISMATCH": 422,
    "ERR_PROGRAM_DESIGN_MISMATCH": 422,
    "ERR_CHARACTERISTIC_DESIGN_MISMATCH": 422,
    "ERR_PPAP_LEVEL_MISMATCH": 422,
    # ---- constraint
    "ERR_WIRE_DIAMETER_EXCEEDS_MACHINE": 422,
    "ERR_INVALID_SUBGROUP_SIZE": 422,
    "ERR_CHARACTERISTIC_SET_EMPTY": 422,
    "ERR_INCOMPLETE_FAI_COVERAGE": 422,
    "ERR_DUPLICATE_CHARACTERISTIC": 409,
    "ERR_DUPLICATE_CODE": 409,
    "ERR_OPEN_SUBMISSION_EXISTS": 409,
    "ERR_NO_QUALIFIED_RUN": 422,
    "ERR_MAX_SUBMISSION_ROUNDS_EXCEEDED": 422,
    "ERR_TEMP_EXCEEDS_OVEN": 422,
    "ERR_BELOW_MINIMUM_ORDER_QUANTITY": 422,
    "ERR_RUN_PIECES_EXHAUSTED": 422,
    # ---- temporal
    "ERR_WINDOW_INVALID": 422,
    "ERR_WINDOW_IN_PAST": 422,
    "ERR_SETUP_WINDOW_CONFLICT": 409,
    "ERR_OUTSIDE_SETUP_WINDOW": 409,
    "ERR_BATCH_WINDOW_NOT_REACHED": 409,
    "ERR_CLOCK_NOT_MONOTONIC": 422,
    # ---- fiscal
    "ERR_OVEN_CAPACITY_EXCEEDED": 409,
    "ERR_INSUFFICIENT_WIRE": 409,
    "ERR_PROGRAM_NOT_QUOTED": 409,
    "ERR_COMMITMENT_EXCEEDED": 422,
    "ERR_INTERIM_PIECE_CAP_EXCEEDED": 422,
    "ERR_TOOLING_NOT_AMORTIZING": 409,
    # ---- fallbacks (not part of the published catalog)
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or invalid authentication headers.",
    "ERR_UNAUTHORIZED": "The acting role is not authorised for this endpoint.",
    "ERR_PROGRAM_OWNERSHIP_MISMATCH": "The target resource belongs to a different customer program.",
    "ERR_INVALID_REQUEST": "The request body is malformed or violates a field constraint.",
    "ERR_INVALID_PAGINATION": "limit must be within [1,100] and offset must be >= 0.",
    "ERR_NOT_FOUND": "The requested resource does not exist.",
    "ERR_METHOD_NOT_ALLOWED": "The HTTP method is not allowed for this path.",
    "ERR_INTERNAL": "Internal server error.",
}
