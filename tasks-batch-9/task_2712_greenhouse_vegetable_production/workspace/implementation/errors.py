"""Error catalog: error_id -> HTTP status, plus the ApiError exception."""

ERROR_HTTP = {
    # --- auth / rbac ---
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_ACTOR_NOT_RECOGNIZED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- validation ---
    "ERR_VALIDATION": 422,
    "ERR_INVALID_ENUM_VALUE": 422,
    # --- not found ---
    "ERR_NOT_FOUND": 404,
    "ERR_ZONE_NOT_FOUND": 404,
    "ERR_VARIETY_NOT_FOUND": 404,
    "ERR_CROP_CYCLE_NOT_FOUND": 404,
    "ERR_CLIMATE_STRATEGY_NOT_FOUND": 404,
    "ERR_FERTIGATION_BATCH_NOT_FOUND": 404,
    "ERR_SCOUTING_OBSERVATION_NOT_FOUND": 404,
    "ERR_BIO_CONTROL_RELEASE_NOT_FOUND": 404,
    "ERR_WORKER_NOT_FOUND": 404,
    "ERR_LABOR_TASK_NOT_FOUND": 404,
    "ERR_HARVEST_LOT_NOT_FOUND": 404,
    "ERR_RETAIL_PROGRAM_NOT_FOUND": 404,
    "ERR_COMMITMENT_WEEK_NOT_FOUND": 404,
    "ERR_LOT_ALLOCATION_NOT_FOUND": 404,
    # --- optimistic concurrency ---
    "ERR_STALE_ZONE_VERSION": 412,
    "ERR_STALE_LOT_VERSION": 412,
    # --- state ---
    "ERR_TERMINAL_STATE": 409,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_CROP_CYCLE_NOT_ACTIVE": 409,
    "ERR_ZONE_OCCUPIED": 409,
    "ERR_PRODUCTION_TOO_EARLY": 422,
    "ERR_TERMINATION_DATE_OUT_OF_RANGE": 422,
    "ERR_OPEN_LABOR_TASKS": 409,
    "ERR_UNGRADED_LOTS_REMAIN": 409,
    "ERR_ACTUALS_ALREADY_RECORDED": 409,
    "ERR_BATCH_NOT_DELIVERED": 409,
    "ERR_NO_DRAIN_READINGS": 409,
    "ERR_WEEK_NOT_ALLOCATED": 409,
    "ERR_WEEK_ALREADY_SHIPPED": 409,
    "ERR_WEEK_STILL_OPEN": 409,
    "ERR_NO_CONFIRMED_ALLOCATIONS": 409,
    "ERR_PROGRAM_NOT_ACTIVE": 409,
    "ERR_TASK_WINDOW_NOT_OPEN": 409,
    "ERR_TASK_WINDOW_STILL_OPEN": 409,
    "ERR_TASK_AFTER_TERMINATION": 422,
    "ERR_LOT_NOT_GRADED": 409,
    "ERR_LOT_NOT_COLD_HELD": 409,
    # --- ipm / safety gates ---
    "ERR_ZONE_IPM_LOCKED": 409,
    "ERR_REENTRY_INTERVAL_ACTIVE": 409,
    "ERR_IRRIGATION_LOCKED": 409,
    "ERR_OBSERVATION_BELOW_THRESHOLD": 409,
    "ERR_OBSERVATION_ZONE_MISMATCH": 409,
    "ERR_RELEASE_COUNT_OUT_OF_TOLERANCE": 422,
    "ERR_RELEASE_BEFORE_OBSERVATION": 422,
    "ERR_MAX_REVISIONS_EXCEEDED": 409,
    "ERR_DECISION_REASON_REQUIRED": 422,
    # --- duplicates ---
    "ERR_ZONE_CODE_DUPLICATE": 409,
    "ERR_PROGRAM_CODE_DUPLICATE": 409,
    "ERR_ISO_WEEK_DUPLICATE": 409,
    # --- climate ---
    "ERR_SETPOINT_OUT_OF_RANGE": 422,
    "ERR_ZONE_CAPABILITY_MISSING": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_CLIMATE_WINDOW_OVERLAP": 409,
    # --- variety / yield ---
    "ERR_YIELD_CURVE_LENGTH_MISMATCH": 422,
    # --- fertigation ---
    "ERR_TARGET_EC_OFF_RECIPE": 422,
    "ERR_DELIVERY_VOLUME_VARIANCE": 422,
    "ERR_READING_OUT_OF_WINDOW": 422,
    # --- harvest / grading ---
    "ERR_MASS_BALANCE_MISMATCH": 422,
    "ERR_PACK_OUT_BELOW_MINIMUM": 422,
    "ERR_ALLOCATED_EXCEEDS_GRADE": 409,
    "ERR_COLD_CHAIN_BREACH": 422,
    "ERR_HARVEST_TOO_EARLY": 422,
    # --- labor ---
    "ERR_WORKER_DOUBLE_BOOKED": 409,
    "ERR_WORKER_INACTIVE": 409,
    "ERR_WORKER_SKILL_MISMATCH": 409,
    "ERR_LABOR_BUDGET_EXCEEDED": 409,
    # --- crop cycle / zone linkage ---
    "ERR_CROP_CYCLE_ZONE_MISMATCH": 409,
    "ERR_HIVE_SLOTS_EXCEEDED": 409,
    # --- commercial ---
    "ERR_NO_ELIGIBLE_LOTS": 422,
    "ERR_INSUFFICIENT_AVAILABLE_LBS": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or empty",
    "ERR_UNAUTHORIZED": "The acting role is not permitted to perform this operation",
    "ERR_ACTOR_NOT_RECOGNIZED": "The acting user does not resolve to a qualified worker",
    "ERR_VALIDATION": "Request payload failed validation",
    "ERR_INVALID_ENUM_VALUE": "A field carries a value outside its declared enumeration",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize()
        )
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        super().__init__(self.message)
