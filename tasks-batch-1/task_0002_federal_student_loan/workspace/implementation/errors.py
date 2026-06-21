"""Custom error class carrying error_id, message, and http_status."""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


# Error catalog constants (per scaffold §1.6 and PRD §5)
ERR_UNAUTHENTICATED          = ("ERR_UNAUTHENTICATED", 401)
ERR_UNAUTHORIZED             = ("ERR_UNAUTHORIZED", 403)
ERR_LOAN_NOT_FOUND           = ("ERR_LOAN_NOT_FOUND", 404)
ERR_BORROWER_NOT_FOUND       = ("ERR_BORROWER_NOT_FOUND", 404)
ERR_RESOURCE_NOT_FOUND       = ("ERR_RESOURCE_NOT_FOUND", 404)
ERR_INVALID_STATE            = ("ERR_INVALID_STATE", 409)
ERR_PLAN_ALREADY_ACTIVE      = ("ERR_PLAN_ALREADY_ACTIVE", 409)
ERR_NOT_VETERAN              = ("ERR_NOT_VETERAN", 422)
ERR_PSLF_INSUFFICIENT_PAYMENTS = ("ERR_PSLF_INSUFFICIENT_PAYMENTS", 422)
ERR_DEFAULT_THRESHOLD_NOT_MET = ("ERR_DEFAULT_THRESHOLD_NOT_MET", 422)
ERR_REHABILITATION_NOT_QUALIFIED = ("ERR_REHABILITATION_NOT_QUALIFIED", 422)
ERR_STALE_LOAN_VERSION       = ("ERR_STALE_LOAN_VERSION", 412)
ERR_STALE_APPLICATION_VERSION = ("ERR_STALE_APPLICATION_VERSION", 412)
ERR_INVALID_PERIOD           = ("ERR_INVALID_PERIOD", 422)
ERR_FUTURE_PAYMENT           = ("ERR_FUTURE_PAYMENT", 422)
ERR_PAYMENT_AMOUNT_OUT_OF_RANGE = ("ERR_PAYMENT_AMOUNT_OUT_OF_RANGE", 422)
ERR_INVALID_REQUEST          = ("ERR_INVALID_REQUEST", 400)


def raise_err(spec, message: str = ""):
    eid, http = spec
    raise ApiError(eid, http, message or eid)
