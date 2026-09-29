"""Error catalogue and the ApiError exception (PRD section 5)."""

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_WINDOW": 400,
    "ERR_WARD_NOT_FOUND": 404,
    "ERR_PATIENT_NOT_FOUND": 404,
    "ERR_DIET_RULE_NOT_FOUND": 404,
    "ERR_DIET_ORDER_NOT_FOUND": 404,
    "ERR_MEAL_PERIOD_NOT_FOUND": 404,
    "ERR_MENU_ITEM_NOT_FOUND": 404,
    "ERR_MEAL_ORDER_NOT_FOUND": 404,
    "ERR_MEAL_ORDER_LINE_NOT_FOUND": 404,
    "ERR_PROCEDURE_HOLD_NOT_FOUND": 404,
    "ERR_CONSULT_NOT_FOUND": 404,
    "ERR_SUPPLEMENT_ORDER_NOT_FOUND": 404,
    "ERR_SURVEY_NOT_FOUND": 404,
    "ERR_WARD_SUSPENDED": 409,
    "ERR_PATIENT_DISCHARGED": 409,
    "ERR_MEAL_PERIOD_CLOSED": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_DIET_ORDER_NOT_ACTIVE": 409,
    "ERR_DIET_ORDER_SUPERSEDED": 409,
    "ERR_CONSULT_NOT_SIGNED": 409,
    "ERR_QA_NOT_PASSED": 409,
    "ERR_STALE_DIET_ORDER_VERSION": 412,
    "ERR_STALE_CONSULT_VERSION": 412,
    "ERR_NPO_ACTIVE": 422,
    "ERR_ALLERGEN_CONFLICT": 422,
    "ERR_TEXTURE_LEVEL_VIOLATION": 422,
    "ERR_LIQUID_LEVEL_VIOLATION": 422,
    "ERR_FORBIDDEN_TAG": 422,
    "ERR_MENU_ITEM_DISCONTINUED": 422,
    "ERR_DIET_RULE_RETIRED": 422,
    "ERR_TEMPERATURE_PROBE_REQUIRED": 422,
    "ERR_ALBUMIN_REQUIRED": 422,
    "ERR_NUTRIENT_CAP_EXCEEDED": 422,
    "ERR_MEAL_PERIOD_WINDOW_OVERLAP": 409,
    "ERR_PROCEDURE_HOLD_OVERLAP": 409,
    "ERR_ORDER_CUTOFF_PASSED": 422,
    "ERR_EMPTY_MEAL_ORDER": 422,
    "ERR_DUPLICATE_MEAL_ORDER": 409,
    "ERR_DUPLICATE_MRN": 409,
    "ERR_DUPLICATE_DIET_RULE_CODE": 409,
    "ERR_DUPLICATE_MENU_ITEM_CODE": 409,
    "ERR_DUPLICATE_WARD_CODE": 409,
    "ERR_MEAL_ORDER_NOT_DELIVERED": 409,
    "ERR_DUPLICATE_SURVEY": 409,
    "ERR_REVISION_LIMIT_EXCEEDED": 422,
    "ERR_TRAY_CAPACITY_EXCEEDED": 409,
    "ERR_PERIOD_COST_CEILING_EXCEEDED": 422,
    # non-catalogue fallback for unrouted paths / methods
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or the role is not recognised.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not permitted to use this endpoint.",
    "ERR_SEGREGATION_OF_DUTIES": "The acting user may not perform this step.",
    "ERR_INVALID_REQUEST": "The request is malformed.",
    "ERR_INVALID_WINDOW": "The supplied interval is not geometrically valid.",
    "ERR_INVALID_STATE": "The resource is not in a state that permits this transition.",
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline; rendered by the Flask error handler."""

    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )
        super().__init__(self.message)
