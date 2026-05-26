"""Error catalogue and ApiError class."""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue from PRD §5 / SCAFFOLD §1.6
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_RESOURCE_OWNER = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_INVALID_PAGINATION = ("ERR_INVALID_PAGINATION", 400)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_HOUSEHOLD_INCOMPLETE = ("ERR_HOUSEHOLD_INCOMPLETE", 422)
ERR_ALLERGEN_CONFLICT = ("ERR_ALLERGEN_CONFLICT", 422)
ERR_NO_ACTIVE_ELIGIBILITY = ("ERR_NO_ACTIVE_ELIGIBILITY", 422)
ERR_INSUFFICIENT_FUNDS = ("ERR_INSUFFICIENT_FUNDS", 422)
ERR_TOPUP_CAP_EXCEEDED = ("ERR_TOPUP_CAP_EXCEEDED", 422)
ERR_DUPLICATE_IDEMPOTENCY_KEY = ("ERR_DUPLICATE_IDEMPOTENCY_KEY", 409)
ERR_CLAIM_PERIOD_OVERLAP = ("ERR_CLAIM_PERIOD_OVERLAP", 409)
ERR_ELIGIBILITY_OVERLAP = ("ERR_ELIGIBILITY_OVERLAP", 409)
ERR_PERIOD_NOT_SETTLED = ("ERR_PERIOD_NOT_SETTLED", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)


def raise_err(spec, message: str = ""):
    error_id, status = spec
    raise ApiError(error_id, status, message or error_id)
