"""Error catalogue (PRD section 5) and the ApiError exception."""

ERROR_HTTP = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_ASSIGNED_REVIEWER": 403,
    # existence
    "ERR_APPLICANT_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_VERIFICATION_NOT_FOUND": 404,
    "ERR_SLOT_NOT_FOUND": 404,
    "ERR_ASSESSMENT_NOT_FOUND": 404,
    "ERR_VEHICLE_NOT_FOUND": 404,
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_DETERMINATION_NOT_FOUND": 404,
    "ERR_APPEAL_NOT_FOUND": 404,
    "ERR_TRIP_EVENT_NOT_FOUND": 404,
    "ERR_PROCEEDING_NOT_FOUND": 404,
    "ERR_REFERRAL_NOT_FOUND": 404,
    "ERR_VISITOR_RECORD_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    # state
    "ERR_INVALID_APPLICATION_STATE": 409,
    "ERR_VERIFICATION_STATE_INVALID": 409,
    "ERR_INVALID_ASSESSMENT_STATE": 409,
    "ERR_DETERMINATION_ALREADY_ISSUED": 409,
    "ERR_DETERMINATION_NOT_APPEALABLE": 409,
    "ERR_DETERMINATION_NOT_ACTIVE": 409,
    "ERR_APPEAL_STATE_INVALID": 409,
    "ERR_PROCEEDING_STATE_INVALID": 409,
    "ERR_REFERRAL_STATE_INVALID": 409,
    "ERR_BOOKING_NOT_CANCELLABLE": 409,
    "ERR_VISITOR_RECORD_INACTIVE": 409,
    # optimistic concurrency
    "ERR_STALE_APPLICATION_VERSION": 412,
    "ERR_STALE_APPLICANT_VERSION": 412,
    # safety / accessibility / segregation of duties
    "ERR_VEHICLE_OUT_OF_SERVICE": 409,
    "ERR_VEHICLE_NOT_ACCESSIBLE": 422,
    "ERR_SITE_NOT_ACCESSIBLE": 422,
    "ERR_SIGNOFF_NOT_INDEPENDENT": 422,
    "ERR_REVIEWER_NOT_INDEPENDENT": 422,
    "ERR_DECIDER_NOT_INDEPENDENT": 422,
    "ERR_DUE_PROCESS_INCOMPLETE": 422,
    "ERR_SUSPENSION_UNSUPPORTED": 422,
    # cross-entity referential
    "ERR_ASSESSMENT_NOT_SIGNED_OFF": 422,
    "ERR_CONDITIONAL_REQUIRES_CONDITIONS": 422,
    "ERR_UNCONDITIONAL_FORBIDS_CONDITIONS": 422,
    "ERR_CATEGORY_NOT_TRAINABLE": 422,
    "ERR_NOT_OUT_OF_AREA": 422,
    "ERR_LOCAL_ELIGIBILITY_EXISTS": 422,
    "ERR_GRANTED_CATEGORY_MISMATCH": 422,
    "ERR_HEARING_REQUIRED": 422,
    "ERR_HEARING_NOT_REQUESTED": 422,
    # constraint satisfaction
    "ERR_DUPLICATE_OPEN_APPLICATION": 409,
    "ERR_VERIFICATION_PENDING": 409,
    "ERR_EVALUATOR_SLOT_CONFLICT": 409,
    "ERR_SLOT_FULL": 409,
    "ERR_VEHICLE_WINDOW_CONFLICT": 409,
    "ERR_VISITOR_DAYS_EXHAUSTED": 409,
    # temporal
    "ERR_APPEAL_WINDOW_CLOSED": 422,
    "ERR_SLOT_IN_PAST": 422,
    "ERR_PICKUP_WINDOW_LATE": 422,
    "ERR_TRIP_DATE_FUTURE": 422,
    "ERR_RESPONSE_WINDOW_CLOSED": 422,
    "ERR_SERVICE_DATE_OUT_OF_RANGE": 422,
    "ERR_SUSPENSION_START_IN_PAST": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Both X-User-ID and a valid X-User-Role header are required.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorized for this operation.",
    "ERR_NOT_RESOURCE_OWNER": "The acting applicant does not own the addressed resource.",
    "ERR_NOT_ASSIGNED_REVIEWER": "Only the appeal's assigned independent reviewer may act.",
    "ERR_INVALID_REQUEST": "The request payload is invalid.",
    "ERR_INVALID_PAGINATION": "limit must be an integer in 1..100 and offset an integer >= 0.",
}
