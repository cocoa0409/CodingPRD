"""Error taxonomy with exact IDs from the scaffold error catalog (§1.6)."""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_CROSS_PLAN_REFERENCE = ("ERR_CROSS_PLAN_REFERENCE", 422)
ERR_INVALID_DATE_RANGE = ("ERR_INVALID_DATE_RANGE", 422)
ERR_CLAIM_WINDOW_AMBIGUITY = ("ERR_CLAIM_WINDOW_AMBIGUITY", 422)
ERR_NOTICE_OUTSTANDING = ("ERR_NOTICE_OUTSTANDING", 422)
ERR_LASER_CONFLICT = ("ERR_LASER_CONFLICT", 422)
ERR_AMOUNT_OUT_OF_RANGE = ("ERR_AMOUNT_OUT_OF_RANGE", 422)
ERR_FILING_DEADLINE_PASSED = ("ERR_FILING_DEADLINE_PASSED", 422)
ERR_REIMBURSEMENT_MISMATCH = ("ERR_REIMBURSEMENT_MISMATCH", 422)
ERR_SEGREGATION_OF_DUTIES = ("ERR_SEGREGATION_OF_DUTIES", 403)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)


def raise_error(spec, message: str = ""):
    error_id, status = spec
    raise ApiError(error_id, status, message or error_id)
