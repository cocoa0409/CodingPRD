"""API error catalog and exception class."""


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (id -> http status). Mirrors §5 of the PRD.
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_PARENT_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_HOUSEHOLD_NOT_ACTIVE": 409,
    "ERR_CARD_NOT_ACTIVE": 409,
    "ERR_NOT_CLAIMING_INVESTIGATOR": 403,
    "ERR_DUPLICATE_CASE_NUMBER": 409,
    "ERR_DUPLICATE_ALLOTMENT_MONTH": 409,
    "ERR_DUPLICATE_WAIVER_QUARTER": 409,
    "ERR_DUPLICATE_PROCLAMATION": 409,
    "ERR_BENEFIT_MONTH_IN_PAST": 422,
    "ERR_ISSUANCE_TOO_EARLY": 409,
    "ERR_INCOME_LIMIT_EXCEEDED": 409,
    "ERR_ABAWD_REQUIREMENT_UNMET": 409,
    "ERR_ALL_ITEMS_INELIGIBLE": 422,
    "ERR_INVALID_LINE_ITEMS": 422,
    "ERR_OUT_OF_STATE_BLOCKED": 409,
    "ERR_STALE_HOUSEHOLD_VERSION": 412,
    "ERR_STALE_FRAUDFLAG_VERSION": 412,
}


def raise_api(error_id: str, message: str = ""):
    http = ERROR_CATALOG.get(error_id, 500)
    raise APIError(error_id, http, message or error_id)
