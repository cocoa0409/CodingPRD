"""Error catalogue (39 codes) and the ApiError exception."""

ERROR_STATUS = {
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_UNKNOWN_ROLE": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_ORIGINATOR_IDENTITY_MISMATCH": 403,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_REFERENCED_RESOURCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_DUPLICATE_KEY": 409,
    "ERR_STALE_LICENSE_VERSION": 412,
    "ERR_STALE_ORIGINATOR_VERSION": 412,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_LICENSE_NOT_ACTIVE": 422,
    "ERR_STATE_NOT_AUTHORIZED": 422,
    "ERR_SPONSORSHIP_REQUIRED": 422,
    "ERR_PROHIBITED_COMP_VARIABLE": 422,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_SECOND_APPROVAL_REQUIRED": 422,
    "ERR_JUSTIFICATION_INSUFFICIENT": 422,
    "ERR_DUAL_COMPENSATION_PROHIBITED": 422,
    "ERR_UNLICENSED_ACTIVITY_OPEN": 422,
    "ERR_AD_DISCLOSURE_INCOMPLETE": 422,
    "ERR_PLAN_NOT_ACTIVE": 422,
    "ERR_NO_ACTIVE_COMP_PLAN": 422,
    "ERR_PLAN_WEIGHTS_NOT_100": 422,
    "ERR_COURSE_PROVIDER_RESCINDED": 422,
    "ERR_COURSE_NOT_APPROVED_IN_STATE": 422,
    "ERR_RENEWAL_WINDOW_CLOSED": 422,
    "ERR_SPONSORSHIP_PERIOD_OVERLAP": 409,
    "ERR_PLAN_PERIOD_OVERLAP": 409,
    "ERR_INVALID_DATE_RANGE": 422,
    "ERR_RESPONSE_DEADLINE_PASSED": 422,
    "ERR_CE_HOURS_INSUFFICIENT": 422,
    "ERR_CONCESSION_EXCEEDS_CAP": 422,
    "ERR_COMP_CAP_EXCEEDED": 422,
    "ERR_RESTITUTION_MISMATCH": 422,
    "ERR_REINSTATEMENT_LIMIT_REACHED": 422,
    "ERR_OPEN_PIPELINE_BLOCKS_SURRENDER": 422,
}

DEFAULT_MESSAGE = {
    "ERR_MISSING_AUTH_HEADERS": "X-User-ID and X-User-Role headers are required.",
    "ERR_UNKNOWN_ROLE": "X-User-Role is not one of the seven recognised roles.",
    "ERR_ROLE_NOT_PERMITTED": "The caller's role may not invoke this endpoint.",
    "ERR_ORIGINATOR_IDENTITY_MISMATCH": "X-User-ID does not match the originator this request acts on.",
    "ERR_RESOURCE_NOT_FOUND": "The requested resource does not exist.",
    "ERR_REFERENCED_RESOURCE_NOT_FOUND": "A referenced resource in the request body does not exist.",
    "ERR_INVALID_REQUEST": "The request body or query string is malformed.",
    "ERR_INVALID_PAGINATION": "Pagination parameters are out of range or not integers.",
    "ERR_DUPLICATE_KEY": "A row with this unique key already exists.",
    "ERR_STALE_LICENSE_VERSION": "expected_license_registration_version does not match the stored version.",
    "ERR_STALE_ORIGINATOR_VERSION": "expected_originator_version does not match the stored version.",
    "ERR_INVALID_STATE_TRANSITION": "The row's current state has no outgoing transition for this action.",
    "ERR_ALREADY_TERMINAL": "The row is already in a terminal state.",
    "ERR_LICENSE_NOT_ACTIVE": "No licence in an authority-bearing status covers this instant.",
    "ERR_STATE_NOT_AUTHORIZED": "The originator is not authorised in the requested state.",
    "ERR_SPONSORSHIP_REQUIRED": "No active sponsorship covers this instant.",
    "ERR_PROHIBITED_COMP_VARIABLE": "The plan carries at least one PROHIBITED compensation variable.",
    "ERR_SEGREGATION_OF_DUTIES": "The acting user may not both request and decide this item.",
    "ERR_SECOND_APPROVAL_REQUIRED": "A distinct second approver is required.",
    "ERR_JUSTIFICATION_INSUFFICIENT": "The justification text is too short for this reason code.",
    "ERR_DUAL_COMPENSATION_PROHIBITED": "Dual compensation is prohibited for this originator.",
    "ERR_UNLICENSED_ACTIVITY_OPEN": "An unlicensed-activity investigation is open for this loan.",
    "ERR_AD_DISCLOSURE_INCOMPLETE": "The advertisement's disclosure findings are not empty.",
    "ERR_PLAN_NOT_ACTIVE": "The referenced compensation plan is not ACTIVE for this instant.",
    "ERR_NO_ACTIVE_COMP_PLAN": "The originator carries no assigned compensation plan.",
    "ERR_PLAN_WEIGHTS_NOT_100": "The plan's variable weights do not sum to exactly 100.",
    "ERR_COURSE_PROVIDER_RESCINDED": "The course provider status is RESCINDED.",
    "ERR_COURSE_NOT_APPROVED_IN_STATE": "The course is not approved in the licence's state.",
    "ERR_RENEWAL_WINDOW_CLOSED": "The renewal window is not open at the current instant.",
    "ERR_SPONSORSHIP_PERIOD_OVERLAP": "The requested sponsorship period overlaps an existing one.",
    "ERR_PLAN_PERIOD_OVERLAP": "The requested plan assignment period collides with an existing one.",
    "ERR_INVALID_DATE_RANGE": "The supplied date range is invalid.",
    "ERR_RESPONSE_DEADLINE_PASSED": "The response deadline has already passed.",
    "ERR_CE_HOURS_INSUFFICIENT": "Continuing-education requirements are not satisfied.",
    "ERR_CONCESSION_EXCEEDS_CAP": "The concession exceeds the permitted cap.",
    "ERR_COMP_CAP_EXCEEDED": "Total compensation exceeds the plan's maximum fee.",
    "ERR_RESTITUTION_MISMATCH": "restitution_cents is inconsistent with the finding.",
    "ERR_REINSTATEMENT_LIMIT_REACHED": "The licence has already been reinstated twice.",
    "ERR_OPEN_PIPELINE_BLOCKS_SURRENDER": "Open pipeline loans block surrender.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGE.get(error_id, error_id)


def bad_request(message=None):
    return ApiError("ERR_INVALID_REQUEST", message)
