"""Error catalogue (PRD section 5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message if message else DEFAULT_MESSAGES.get(error_id, error_id)


# error_id -> http status
ERROR_STATUS = {
    # 401
    "ERR_UNAUTHENTICATED": 401,
    # 403
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # 400
    "ERR_INVALID_REQUEST": 400,
    # 404
    "ERR_CIRCUIT_NOT_FOUND": 404,
    "ERR_WEATHER_STATION_NOT_FOUND": 404,
    "ERR_FIRE_POTENTIAL_INDEX_NOT_FOUND": 404,
    "ERR_PSPS_EVENT_NOT_FOUND": 404,
    "ERR_EVENT_SCOPE_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_NOTIFICATION_BATCH_NOT_FOUND": 404,
    "ERR_NOTIFICATION_RECORD_NOT_FOUND": 404,
    "ERR_MITIGATION_PROJECT_NOT_FOUND": 404,
    "ERR_PATROL_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_RESOURCE_CENTER_NOT_FOUND": 404,
    "ERR_PLAN_FILING_NOT_FOUND": 404,
    # 412
    "ERR_STALE_VERSION": 412,
    # 409
    "ERR_EVENT_NOT_SCOPED": 409,
    "ERR_EVENT_NOT_ARMED": 409,
    "ERR_EVENT_NOT_ACTIVE": 409,
    "ERR_EVENT_NOT_IN_RESTORATION": 409,
    "ERR_EVENT_TERMINAL": 409,
    "ERR_EVENT_NOT_CANCELLABLE": 409,
    "ERR_SCOPE_ALREADY_EXCLUDED": 409,
    "ERR_BATCH_ALREADY_DISPATCHED": 409,
    "ERR_PROJECT_INVALID_STATE": 409,
    "ERR_PATROL_INVALID_STATE": 409,
    "ERR_FILING_INVALID_STATE": 409,
    "ERR_REVIEW_TRACK_ALREADY_DECIDED": 409,
    "ERR_CIRCUIT_NOT_CLEARED_FOR_RESTORE": 409,
    "ERR_RESOURCE_CENTER_ALREADY_ACTIVE": 409,
    "ERR_CIRCUIT_POSTURE_LOCKED": 409,
    "ERR_CIRCUIT_NOT_DE_ENERGIZED": 409,
    "ERR_DUPLICATE_CODE": 409,
    "ERR_CIRCUIT_WINDOW_CONFLICT": 409,
    "ERR_RESOURCE_CENTER_BUFFER_CONFLICT": 409,
    "ERR_PATROL_WINDOW_OVERLAP": 409,
    # 422
    "ERR_IGNITION_RISK_DAMAGE_UNRESOLVED": 422,
    "ERR_PATROL_NOT_COMPLETED": 422,
    "ERR_ADVANCE_NOTIFICATION_MISSING": 422,
    "ERR_CRITICAL_NOTIFICATION_INCOMPLETE": 422,
    "ERR_EVENT_WINDOW_INVALID": 422,
    "ERR_PATROL_WINDOW_INVALID": 422,
    "ERR_NOTIFICATION_WINDOW_INVALID": 422,
    "ERR_NOTIFICATION_LEAD_TIME_SHORT": 422,
    "ERR_NO_CIRCUITS_IN_SCOPE": 422,
    "ERR_NO_QUALIFYING_CIRCUITS": 422,
    "ERR_OBSERVATION_WINDOW_EMPTY": 422,
    "ERR_FILING_METRICS_INCOMPLETE": 422,
    "ERR_NET_BENEFIT_BELOW_THRESHOLD": 422,
    "ERR_MITIGATION_MILES_EXCEEDED": 422,
    "ERR_REVIEW_ROUND_LIMIT": 422,
    "ERR_NO_ELIGIBLE_RESOURCE_CENTER": 422,
    "ERR_RESOURCE_CENTER_DISTRICT_MISMATCH": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or the role is unrecognised.",
    "ERR_FORBIDDEN_ROLE": "The acting role may not perform this operation.",
    "ERR_SEGREGATION_OF_DUTIES": "The acting identity may not decide this step.",
    "ERR_INVALID_REQUEST": "The request is not well formed.",
    "ERR_CIRCUIT_NOT_FOUND": "Circuit not found.",
    "ERR_WEATHER_STATION_NOT_FOUND": "Weather station not found.",
    "ERR_FIRE_POTENTIAL_INDEX_NOT_FOUND": "Fire potential index not found.",
    "ERR_PSPS_EVENT_NOT_FOUND": "Shutoff event not found.",
    "ERR_EVENT_SCOPE_NOT_FOUND": "Event scope not found.",
    "ERR_CUSTOMER_NOT_FOUND": "Customer not found.",
    "ERR_NOTIFICATION_BATCH_NOT_FOUND": "Notification batch not found.",
    "ERR_NOTIFICATION_RECORD_NOT_FOUND": "Notification record not found.",
    "ERR_MITIGATION_PROJECT_NOT_FOUND": "Mitigation project not found.",
    "ERR_PATROL_ASSIGNMENT_NOT_FOUND": "Patrol assignment not found.",
    "ERR_RESOURCE_CENTER_NOT_FOUND": "Community resource center not found.",
    "ERR_PLAN_FILING_NOT_FOUND": "Wildfire plan filing not found.",
    "ERR_STALE_VERSION": "The supplied expected version does not match the stored version.",
    "ERR_DUPLICATE_CODE": "A natural key in the request is already taken.",
}


def api_error(error_id, message=None):
    return ApiError(error_id, message)


def invalid(message="The request is not well formed."):
    return ApiError("ERR_INVALID_REQUEST", message)
