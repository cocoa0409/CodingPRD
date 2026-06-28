"""Error catalog and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> (http_status, default message)
ERRORS = {
    "ERR_UNAUTHENTICATED": (401, "Missing or invalid authentication headers."),
    "ERR_FORBIDDEN_ROLE": (403, "Acting role is not permitted for this operation."),
    "ERR_NOT_RESOURCE_OWNER": (403, "Acting customer does not own the target project."),
    "ERR_RESOURCE_NOT_FOUND": (404, "Referenced resource does not exist."),
    "ERR_INVALID_STATE": (409, "Target resource is not in a valid state for this transition."),
    "ERR_STALE_PROJECT_VERSION": (412, "expected_project_version does not match current project version."),
    "ERR_STALE_QUOTE_VERSION": (412, "expected_quote_version does not match current quote version."),
    "ERR_CREW_REGION_MISMATCH": (409, "Crew region does not match the project install region."),
    "ERR_MEASURE_ALREADY_CONFIRMED": (409, "Space measure already backs a finalized configuration."),
    "ERR_LEAD_TIME_NOT_ELAPSED": (409, "Manufacture order cannot complete before its promised ready date."),
    "ERR_WINDOW_BEFORE_READY": (409, "Install window starts before the manufacture order is promised ready."),
    "ERR_INVALID_WINDOW": (422, "Install window is invalid."),
    "ERR_QUOTE_EXPIRED": (409, "Quote has expired."),
    "ERR_CREW_CAPACITY_EXCEEDED": (409, "Crew daily capacity would be exceeded."),
    "ERR_WARRANTY_NOT_COVERED": (409, "Warranty claim is not covered."),
    "ERR_WARRANTY_BRANCH_MISMATCH": (409, "Warranty branch does not match the defect type."),
    "ERR_DEPOSIT_BELOW_MINIMUM": (422, "Deposit amount is below the required minimum."),
    "ERR_FINANCE_EXCEEDS_TOTAL": (422, "Financing requested amount exceeds the quote total."),
    "ERR_CONFIG_NOT_FINALIZED": (409, "Component configuration is not finalized."),
    "ERR_CHANGE_TARGET_INVALID": (422, "Change order target is invalid."),
    "ERR_VALIDATION": (422, "Request body is malformed or has invalid fields."),
    "ERR_FINANCE_ALREADY_LINKED": (409, "Project already has a funded financing application."),
}


def err(error_id: str, message: str = "") -> ApiError:
    http = ERRORS.get(error_id, (400, ""))[0]
    default_msg = ERRORS.get(error_id, (400, error_id))[1]
    return ApiError(error_id, http, message or default_msg)
