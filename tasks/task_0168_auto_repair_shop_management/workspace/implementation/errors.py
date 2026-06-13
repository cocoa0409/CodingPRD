"""Error classes and error-id -> HTTP status mapping.

Every error_id and HTTP status below traces verbatim to PRD Section 5
(Error Code Catalogue) and SCAFFOLD 1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status if http_status is not None else ERROR_STATUS[error_id]


# error_id -> HTTP status (PRD Section 5)
ERROR_STATUS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_FORBIDDEN_FOR_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCED_ENTITY_NOT_FOUND": 422,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_BAY_NOT_ASSIGNED": 409,
    "ERR_BAY_DOUBLE_BOOKED": 409,
    "ERR_LABOR_NOT_DONE": 409,
    "ERR_INSPECTION_NOT_SUBMITTED": 409,
    "ERR_RED_WORK_UNRESOLVED": 409,
    "ERR_CORE_OUTSTANDING": 409,
    "ERR_NOTHING_TO_AUTHORIZE": 409,
    "ERR_RO_NOT_EDITABLE": 409,
    "ERR_INSPECTION_EMPTY": 409,
    "ERR_MARKUP_TIER_MISSING": 409,
    "ERR_TECH_DOUBLE_CLOCKED": 409,
    "ERR_OPEN_TIME_ENTRY": 409,
    "ERR_WARRANTY_EXPIRED": 409,
    "ERR_DUPLICATE_VIN": 409,
    "ERR_STALE_VERSION": 412,
}
