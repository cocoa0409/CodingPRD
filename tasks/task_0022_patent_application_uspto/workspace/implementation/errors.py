"""API error catalog and exception class. Mirrors §1.6 of the scaffold."""


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (id -> http status). Mirrors §5 of the PRD / §1.6 of the scaffold.
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_TERMINAL_STATE": 409,
    "ERR_CONTINUATION_TYPE_MISMATCH": 422,
    "ERR_CONTINUATION_PARENT_TERMINAL": 409,
    "ERR_MICRO_INELIGIBLE": 422,
    "ERR_PCT_NATIONAL_PHASE_LATE": 422,
    "ERR_PROVISIONAL_CONVERSION_LATE": 422,
    "ERR_PROVISIONAL_ALREADY_CONVERTED": 409,
    "ERR_MAINTENANCE_WINDOW_CLOSED": 409,
    "ERR_FEE_AMOUNT_MISMATCH": 422,
    "ERR_CLAIM_COUNTS_INVALID": 422,
    "ERR_MAINTENANCE_OUT_OF_ORDER": 409,
    "ERR_EXTENSION_MONTHS_INVALID": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_REQUEST": 400,
    "ERR_OFFICE_ACTION_ALREADY_OUTSTANDING": 409,
    "ERR_PCT_PHASE_ENTRY_DUPLICATE": 409,
}


def raise_api(error_id: str, message: str = ""):
    http = ERROR_CATALOG.get(error_id, 500)
    raise APIError(error_id, http, message or error_id)
