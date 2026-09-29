"""Error catalogue (PRD §5) and the API exception type."""

ERROR_HTTP_STATUS = {
    # identity and authorization
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_COMMITTEE_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_SPECIFICATION_NOT_FOUND": 404,
    "ERR_CLAUSE_NOT_FOUND": 404,
    "ERR_COMPLIANCE_ENTRY_NOT_FOUND": 404,
    "ERR_UNIT_ORDER_NOT_FOUND": 404,
    "ERR_SLOT_LINE_NOT_FOUND": 404,
    "ERR_RESERVATION_NOT_FOUND": 404,
    "ERR_PLANT_BAY_NOT_FOUND": 404,
    "ERR_INSPECTION_TRIP_NOT_FOUND": 404,
    "ERR_CHANGE_ORDER_NOT_FOUND": 404,
    "ERR_CERTIFICATION_TEST_NOT_FOUND": 404,
    "ERR_WARRANTY_STARTUP_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_UNIT_ORDER_VERSION": 412,
    "ERR_STALE_SLOT_LINE_VERSION": 412,
    # own state
    "ERR_INVALID_PROGRAM_STATE": 409,
    "ERR_INVALID_SPEC_STATE": 409,
    "ERR_INVALID_ENTRY_STATE": 409,
    "ERR_INVALID_BUILD_STATE": 409,
    "ERR_UNIT_NOT_AMENDABLE": 409,
    "ERR_INVALID_CERTIFICATION_STATE": 409,
    "ERR_INVALID_TEST_STATE": 409,
    "ERR_INVALID_RESERVATION_STATE": 409,
    "ERR_RESERVATION_UNASSIGNED": 409,
    "ERR_INVALID_TRIP_STATE": 409,
    "ERR_INVALID_CHANGE_ORDER_STATE": 409,
    "ERR_INVALID_WARRANTY_STATE": 409,
    # cross-entity state
    "ERR_PROGRAM_NOT_ACTIVE": 409,
    "ERR_CHASSIS_NOT_CONFIRMED": 409,
    "ERR_MID_CON_INSPECTION_NOT_HELD": 409,
    "ERR_INSPECTION_TRIP_NOT_HELD": 409,
    # referential integrity
    "ERR_TEST_STANDARD_MISMATCH": 422,
    "ERR_TRIP_UNIT_MISMATCH": 422,
    "ERR_SPEC_NOT_RELEASED": 409,
    "ERR_SPEC_PROGRAM_MISMATCH": 422,
    "ERR_PREDECESSOR_NOT_RELEASED": 409,
    "ERR_RESERVATION_UNIT_MISMATCH": 422,
    # safety
    "ERR_AXLE_LOAD_EXCEEDED": 422,
    "ERR_CERTIFICATION_NOT_PASSED": 409,
    # constraint / capacity
    "ERR_SPEC_HAS_NO_CLAUSES": 422,
    "ERR_RESTRICTIVE_CLAUSE_RATIO_EXCEEDED": 422,
    "ERR_SPEC_COMPLIANCE_BELOW_THRESHOLD": 422,
    "ERR_INVALID_SLOT_WINDOW": 422,
    "ERR_INVALID_TRIP_WINDOW": 422,
    "ERR_DELIVERY_BEFORE_MID_CON": 422,
    "ERR_SLOT_WINDOW_CONFLICT": 409,
    "ERR_SLOT_LINE_EXHAUSTED": 409,
    "ERR_BAY_CAPACITY_EXCEEDED": 409,
    "ERR_TRIP_TYPE_ALREADY_HELD": 409,
    "ERR_DUPLICATE_CLAUSE_CODE": 409,
    "ERR_DUPLICATE_COMPLIANCE_ENTRY": 409,
    "ERR_OPEN_CHANGE_ORDERS": 409,
    "ERR_MARKUP_CAP_EXCEEDED": 422,
    "ERR_OPTION_LIMIT_EXCEEDED": 409,
    "ERR_TRAINING_HOURS_NOT_MET": 422,
    "ERR_UNITS_NOT_TERMINAL": 409,
    "ERR_SOFT_CEILING_STILL_BREACHED": 409,
    # fiscal
    "ERR_CONTRACT_CEILING_EXCEEDED": 409,
    "ERR_ESCALATION_YEAR_OUT_OF_RANGE": 422,
}

DEFAULT_MESSAGES = {
    "ERR_MISSING_AUTH_HEADERS": "X-User-ID and X-User-Role headers are required and the role must be a declared role.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not authorised for this operation.",
    "ERR_COMMITTEE_SCOPE_VIOLATION": "The committee representative may only act on resources of its own program.",
    "ERR_SEGREGATION_OF_DUTIES": "Separation of duties forbids the same identity on both sides of this control.",
    "ERR_INVALID_REQUEST": "The request body or query parameters are invalid.",
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline; rendered by the Flask handler."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )
