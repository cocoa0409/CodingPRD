"""Error catalog and the ApiError exception type.

Every error_id and its HTTP status comes verbatim from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status per error_id (PRD §5 Error Code Catalogue).
ERROR_HTTP = {
    # auth
    "ERR_MISSING_OR_INVALID_USER_CONTEXT": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    # existence (404)
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_SURFACE_NOT_FOUND": 404,
    "ERR_LINE_ITEM_NOT_FOUND": 404,
    "ERR_COLOR_SELECTION_NOT_FOUND": 404,
    "ERR_CHANGE_ORDER_NOT_FOUND": 404,
    "ERR_CREW_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_PAYMENT_NOT_FOUND": 404,
    "ERR_WALKTHROUGH_NOT_FOUND": 404,
    "ERR_WARRANTY_CLAIM_NOT_FOUND": 404,
    "ERR_CREW_MEMBER_NOT_FOUND": 404,
    "ERR_EQUIPMENT_NOT_FOUND": 404,
    "ERR_PAINT_PRODUCT_NOT_FOUND": 404,
    "ERR_WEATHER_WINDOW_NOT_FOUND": 404,
    # request validation
    "ERR_INVALID_REQUEST": 422,
    # project state
    "ERR_PROJECT_NOT_DRAFT": 409,
    "ERR_NO_SURFACES": 409,
    "ERR_PROJECT_NOT_ESTIMATED": 409,
    "ERR_DEPOSIT_NOT_PAID": 409,
    "ERR_COLOR_NOT_APPROVED": 409,
    "ERR_NO_CREW_SCHEDULED": 409,
    "ERR_PROJECT_NOT_SCHEDULED": 409,
    "ERR_PROJECT_NOT_IN_PROGRESS": 409,
    "ERR_CREW_NOT_DONE": 409,
    "ERR_PROJECT_NOT_IN_WALKTHROUGH": 409,
    "ERR_BALANCE_OUTSTANDING": 409,
    "ERR_PROJECT_NOT_CANCELLABLE": 409,
    "ERR_PROJECT_NOT_CHANGEABLE": 409,
    # payment state/fiscal
    "ERR_DEPOSIT_ALREADY_PAID": 409,
    "ERR_FINAL_BEFORE_DEPOSIT": 409,
    "ERR_DEPOSIT_AMOUNT_MISMATCH": 402,
    "ERR_FINAL_AMOUNT_MISMATCH": 402,
    # change order state
    "ERR_CHANGE_ORDER_NOT_DRAFT": 409,
    "ERR_CHANGE_ORDER_NOT_SUBMITTED": 409,
    "ERR_CHANGE_ORDER_NOT_REJECTED": 409,
    "ERR_STALE_PROJECT_VERSION": 412,
    # color/surface state
    "ERR_COLOR_NOT_PROPOSED": 409,
    "ERR_SURFACE_NOT_PLANNED": 409,
    "ERR_PRODUCT_SURFACE_MISMATCH": 422,
    # crew/equipment/weather
    "ERR_ASSIGNMENT_NOT_SCHEDULED": 409,
    "ERR_ASSIGNMENT_NOT_IN_PROGRESS": 409,
    "ERR_ASSIGNMENT_NOT_CANCELLABLE": 409,
    "ERR_CREW_SKILL_INSUFFICIENT": 422,
    "ERR_CREW_DOUBLE_BOOKED": 409,
    "ERR_EQUIPMENT_OVERBOOKED": 409,
    "ERR_WEATHER_UNSUITABLE": 422,
    # walkthrough/warranty state
    "ERR_WALKTHROUGH_NOT_PENDING": 409,
    "ERR_WALKTHROUGH_NOT_FAILED": 409,
    "ERR_PUNCH_LIST_OPEN": 409,
    "ERR_CLAIM_NOT_FILED": 409,
    "ERR_CLAIM_NOT_APPROVED": 409,
    "ERR_TOUCHUP_HOURS_REQUIRED": 422,
    "ERR_WARRANTY_EXPIRED": 409,
    "ERR_PROJECT_NOT_COMPLETED": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP[error_id], message)
