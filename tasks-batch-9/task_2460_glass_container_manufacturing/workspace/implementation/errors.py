"""Error catalogue for the Glass Container Manufacturing API (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


# error_id -> http status, straight from the PRD section 5 catalogue.
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_MISSING_USER_ID": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_CUSTOMER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_VALIDATION": 400,
    "ERR_FURNACE_NOT_FOUND": 404,
    "ERR_CAMPAIGN_NOT_FOUND": 404,
    "ERR_BATCH_RECIPE_NOT_FOUND": 404,
    "ERR_COLOR_CHANGE_NOT_FOUND": 404,
    "ERR_FORMING_MACHINE_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_BOTTLE_DESIGN_NOT_FOUND": 404,
    "ERR_MOLD_SET_NOT_FOUND": 404,
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_PRODUCTION_JOB_NOT_FOUND": 404,
    "ERR_PACK_LOT_NOT_FOUND": 404,
    "ERR_COMPLAINT_NOT_FOUND": 404,
    "ERR_CAMPAIGN_STATE_INVALID": 409,
    "ERR_CAMPAIGN_NOT_ACTIVE": 409,
    "ERR_JOB_STATE_INVALID": 409,
    "ERR_MOLD_SET_STATE_INVALID": 409,
    "ERR_DESIGN_STATE_INVALID": 409,
    "ERR_DESIGN_NOT_APPROVED": 409,
    "ERR_RECIPE_NOT_APPROVED": 409,
    "ERR_PROGRAM_STATE_INVALID": 409,
    "ERR_LOT_STATE_INVALID": 409,
    "ERR_COMPLAINT_STATE_INVALID": 409,
    "ERR_COLOR_CHANGE_STATE_INVALID": 409,
    "ERR_FURNACE_POSTURE_BLOCKED": 409,
    "ERR_FURNACE_CAMPAIGN_CONFLICT": 409,
    "ERR_RUNNING_JOB_PRESENT": 409,
    "ERR_OPEN_JOBS_PRESENT": 409,
    "ERR_OPEN_LOTS_PRESENT": 409,
    "ERR_MACHINE_WINDOW_CONFLICT": 409,
    "ERR_COLOR_CHANGE_WINDOW_CONFLICT": 409,
    "ERR_COLOR_CHANGE_RATE_EXCEEDED": 409,
    "ERR_WINDOW_NOT_ELAPSED": 409,
    "ERR_CODE_NOT_UNIQUE": 409,
    "ERR_CAVITY_CAPACITY_EXCEEDED": 409,
    "ERR_NO_INSPECTION_RECORDS": 409,
    "ERR_PALLET_STANDARD_MISMATCH": 409,
    "ERR_PULL_CAPACITY_EXCEEDED": 409,
    "ERR_STALE_FURNACE_VERSION": 412,
    "ERR_STALE_DESIGN_VERSION": 412,
    "ERR_CULLET_RATIO_UNSAFE": 422,
    "ERR_COLOR_MISMATCH": 422,
    "ERR_OVER_PULL_LIMIT": 422,
    "ERR_RISK_INDEX_ABOVE_CAP": 422,
    "ERR_RISK_DELTA_ABOVE_CAP": 422,
    "ERR_FURNACE_MISMATCH": 422,
    "ERR_MOLD_SET_DESIGN_MISMATCH": 422,
    "ERR_TARGET_WEIGHT_NOT_LIGHTER": 422,
    "ERR_LOT_CUSTOMER_MISMATCH": 422,
    "ERR_WINDOW_ORDER_INVALID": 422,
    "ERR_JOB_WINDOW_OUTSIDE_CAMPAIGN": 422,
    "ERR_REJECTS_EXCEED_PACKED": 422,
    "ERR_AFFECTED_UNITS_EXCEED_LOT": 422,
    "ERR_TARGET_PULL_EXCEEDS_DESIGN": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-Role header is missing or is not one of the seven declared roles.",
    "ERR_MISSING_USER_ID": "X-User-ID header is missing or empty.",
    "ERR_ROLE_NOT_PERMITTED": "The caller's role is not authorised for this operation.",
    "ERR_CUSTOMER_SCOPE_VIOLATION": "A CustomerRep may only act on its own customer's resources.",
    "ERR_SEGREGATION_OF_DUTIES": "The second actor of a two-person control must differ from the first.",
    "ERR_VALIDATION": "Request payload or query parameters failed field-level validation.",
    "ERR_WINDOW_ORDER_INVALID": "window_end_at must be strictly after window_start_at.",
}


def fail(error_id, message=None):
    raise ApiError(error_id, ERROR_STATUS[error_id], message)
