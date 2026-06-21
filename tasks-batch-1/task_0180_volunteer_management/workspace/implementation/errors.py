"""Error catalog — error_id -> HTTP status, and the ApiError exception.

Status codes come from PRD §5 / SCAFFOLD errors table. Every error raised by the
application carries one of these ids; the http status is looked up here unless an
explicit override is passed.
"""


# error_id -> HTTP status (PRD §5 / SCAFFOLD §Table 6)
ERROR_STATUS = {
    # --- Auth ---
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_SIGNUP_OWNER": 403,
    # --- Request shape ---
    "ERR_INVALID_REQUEST": 400,
    # --- Not found ---
    "ERR_ORGANIZATION_NOT_FOUND": 404,
    "ERR_VOLUNTEER_NOT_FOUND": 404,
    "ERR_BG_CHECK_NOT_FOUND": 404,
    "ERR_SKILL_NOT_FOUND": 404,
    "ERR_WAIVER_TEMPLATE_NOT_FOUND": 404,
    "ERR_TRAINING_MODULE_NOT_FOUND": 404,
    "ERR_OPPORTUNITY_NOT_FOUND": 404,
    "ERR_SHIFT_NOT_FOUND": 404,
    "ERR_SIGNUP_NOT_FOUND": 404,
    "ERR_GROUP_NOT_FOUND": 404,
    # --- Org / volunteer state ---
    "ERR_ORGANIZATION_ARCHIVED": 409,
    "ERR_VOLUNTEER_NOT_ELIGIBLE": 403,
    # --- BackgroundCheck state ---
    "ERR_BG_CHECK_NOT_INITIATED": 409,
    "ERR_BG_CHECK_NOT_IN_PROGRESS": 409,
    "ERR_BG_CHECK_NOT_EXPIRED": 409,
    "ERR_INVALID_BG_DECISION": 400,
    # --- Opportunity / shift state ---
    "ERR_OPPORTUNITY_NOT_DRAFT": 409,
    "ERR_OPPORTUNITY_NOT_PUBLISHED": 409,
    "ERR_OPPORTUNITY_HAS_NO_SHIFTS": 409,
    "ERR_OPPORTUNITY_NOT_GROUP_EVENT": 409,
    "ERR_SHIFT_NOT_CANCELLABLE": 409,
    "ERR_SHIFT_NOT_COMPLETABLE": 409,
    "ERR_SHIFT_NOT_ENDED": 409,
    "ERR_SHIFT_NOT_STARTED": 409,
    "ERR_SHIFT_NOT_OPEN": 409,
    "ERR_INVALID_SHIFT_TIMES": 400,
    "ERR_INVALID_CAPACITY": 400,
    # --- Signup state + eligibility ---
    "ERR_SIGNUP_NOT_RESERVED": 409,
    "ERR_SIGNUP_NOT_CONFIRMED": 409,
    "ERR_SIGNUP_NOT_ATTENDED": 409,
    "ERR_SIGNUP_NOT_LOGGED": 409,
    "ERR_SIGNUP_NOT_CANCELLABLE": 409,
    "ERR_DUPLICATE_SIGNUP": 409,
    "ERR_SHIFT_FULL": 409,
    "ERR_SHIFT_TIME_CONFLICT": 409,
    "ERR_INVALID_HOURS": 400,
    "ERR_HOURS_EXCEED_SHIFT": 422,
    # --- Prerequisite gates ---
    "ERR_BG_TIER_INSUFFICIENT": 403,
    "ERR_SKILL_REQUIREMENT_NOT_MET": 403,
    "ERR_WAIVER_NOT_ACCEPTED": 403,
    "ERR_TRAINING_NOT_COMPLETED": 403,
    # --- CorporateGroup state ---
    "ERR_GROUP_NOT_PROPOSED": 409,
    "ERR_GROUP_NOT_APPROVED": 409,
    "ERR_GROUP_NOT_CANCELLABLE": 409,
    "ERR_INSUFFICIENT_SHIFT_CAPACITY": 409,
    "ERR_INVALID_SEATS": 400,
    # --- OCC ---
    "ERR_STALE_SHIFT_VERSION": 412,
    "ERR_STALE_VOLUNTEER_VERSION": 412,
    "ERR_STALE_ORGANIZATION_VERSION": 412,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = (http_status if http_status is not None
                            else ERROR_STATUS.get(error_id, 400))


def err(error_id, message=None):
    return ApiError(error_id, message)
