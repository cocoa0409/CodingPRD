"""Error catalogue (PRD section 5).  error_id -> HTTP status."""

ERROR_STATUS = {
    # authentication and authorisation
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_IDENTITY_NOT_RECOGNIZED": 403,
    "ERR_NOT_PROJECT_ENGINEER": 403,
    "ERR_NOT_ASSIGNED_REVIEWER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # existence
    "ERR_ENGINEER_NOT_FOUND": 404,
    "ERR_REVIEWER_NOT_FOUND": 404,
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_HAZARD_AREA_NOT_FOUND": 404,
    "ERR_FLOW_TEST_NOT_FOUND": 404,
    "ERR_CALCULATION_NOT_FOUND": 404,
    "ERR_EVALUATION_NOT_FOUND": 404,
    "ERR_FIRE_PUMP_NOT_FOUND": 404,
    "ERR_AUXILIARY_SYSTEM_NOT_FOUND": 404,
    "ERR_SHOP_DRAWING_NOT_FOUND": 404,
    "ERR_TRADE_CLEARANCE_NOT_FOUND": 404,
    "ERR_SUBMITTAL_NOT_FOUND": 404,
    "ERR_REVIEW_COMMENT_NOT_FOUND": 404,
    "ERR_ACCEPTANCE_TEST_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 422,
    "ERR_SYSTEM_TYPE_FIELD_REQUIRED": 422,
    # optimistic concurrency
    "ERR_STALE_PROJECT_VERSION": 412,
    "ERR_STALE_SUPPLY_EVALUATION_VERSION": 412,
    # posture and state
    "ERR_PROJECT_POSTURE_FROZEN": 409,
    "ERR_PROJECT_POSTURE_GATED": 409,
    "ERR_TERMINAL_STATE_LOCKED": 409,
    "ERR_INVALID_STATE_TRANSITION": 409,
    # life safety
    "ERR_SEAL_LICENSE_INACTIVE": 409,
    "ERR_SEAL_LICENSE_JURISDICTION_MISMATCH": 409,
    "ERR_INTERLOCK_NOT_VERIFIED": 409,
    "ERR_VELOCITY_LIMIT_EXCEEDED": 422,
    "ERR_SAFETY_MARGIN_UNRESOLVED": 409,
    # referential integrity between design artefacts
    "ERR_FLOW_TEST_STALE": 422,
    "ERR_EVALUATION_REFERENCE_STALE": 409,
    "ERR_SUPPLY_FLOW_MISMATCH": 422,
    "ERR_CALCULATION_NOT_SEALED": 409,
    "ERR_DRAWING_NOT_COORDINATED": 409,
    "ERR_DRAWING_NOT_ISSUED": 409,
    "ERR_NO_GOVERNING_CALCULATION": 409,
    "ERR_IN_RACK_HAZARD_MISMATCH": 422,
    "ERR_PUMP_NOT_REQUIRED": 409,
    "ERR_PUMP_ALREADY_SIZED": 409,
    # domain constraints
    "ERR_ROOM_DESIGN_NOT_PERMITTED": 422,
    "ERR_ITERATION_OUT_OF_SEQUENCE": 409,
    "ERR_CHAIN_RESTART_REQUIRED": 409,
    "ERR_NO_ITERATIONS_IN_CHAIN": 409,
    "ERR_DUPLICATE_TRADE_CLEARANCE": 409,
    "ERR_PUMP_CAPACITY_UNAVAILABLE": 422,
    "ERR_RESUBMITTAL_CYCLE_LIMIT": 409,
    # temporal
    "ERR_WINDOW_START_NOT_BEFORE_END": 422,
    "ERR_WITNESS_WINDOW_IN_PAST": 422,
    "ERR_WITNESS_WINDOW_CONFLICT": 409,
    "ERR_OUTAGE_CONCURRENCY_EXCEEDED": 409,
    # fiscal
    "ERR_REVIEW_FEE_OUTSTANDING": 402,
    "ERR_FEE_PAYMENT_EXCEEDS_BALANCE": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or blank.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not authorised for this endpoint.",
    "ERR_IDENTITY_NOT_RECOGNIZED": "The supplied X-User-ID does not resolve to a known row.",
    "ERR_NOT_PROJECT_ENGINEER": "The acting engineer is not the project's lead engineer.",
    "ERR_NOT_ASSIGNED_REVIEWER": "The acting reviewer is not the project's assigned reviewer.",
    "ERR_SEGREGATION_OF_DUTIES": "The author of a calculation may not QC-review it.",
    "ERR_INVALID_REQUEST": "The request body or query does not conform to the endpoint schema.",
}
