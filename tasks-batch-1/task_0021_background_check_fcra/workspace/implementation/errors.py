"""API error catalog and exception class for background-check FCRA service."""


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (id -> http status). Mirrors §1.6 of the scaffold / §5 of the PRD.
ERROR_CATALOG = {
    "ERR_MISSING_AUTH": 401,
    "ERR_INVALID_ROLE": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_BAN_THE_BOX_PREMATURE_INQUIRY": 422,
    "ERR_SALARY_HISTORY_DISCLOSED_BANNED": 422,
    "ERR_CONSENT_NOT_GRANTED": 422,
    "ERR_CONSENT_REVOKE_TOO_LATE": 422,
    "ERR_DUPLICATE_VERIFICATION_TYPE": 422,
    "ERR_WAITING_PERIOD_NOT_ELAPSED": 422,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_BELOW_FEDERAL_FLOOR": 422,
    "ERR_CONSENT_ALREADY_OPEN": 422,
}


def raise_api(error_id: str, message: str = ""):
    http = ERROR_CATALOG.get(error_id, 500)
    raise APIError(error_id, http, message or error_id)
