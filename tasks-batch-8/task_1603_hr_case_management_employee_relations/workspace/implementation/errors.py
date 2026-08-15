"""Error taxonomy — exact error IDs and HTTP statuses from the PRD §5 catalogue."""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# auth
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_UNAUTHORIZED = ("ERR_UNAUTHORIZED", 403)
# existence
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_REFERENCED_NOT_FOUND = ("ERR_REFERENCED_NOT_FOUND", 422)
# state
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_LITIGATION_HOLD = ("ERR_LITIGATION_HOLD", 409)
# business safety
ERR_SEGREGATION_OF_DUTIES = ("ERR_SEGREGATION_OF_DUTIES", 422)
ERR_INVESTIGATOR_CONFLICT = ("ERR_INVESTIGATOR_CONFLICT", 422)
ERR_CERTIFICATION_INSUFFICIENT = ("ERR_CERTIFICATION_INSUFFICIENT", 422)
ERR_CONFIDENTIALITY_VIOLATION = ("ERR_CONFIDENTIALITY_VIOLATION", 422)
# business temporal
ERR_INTERVIEW_OVERLAP = ("ERR_INTERVIEW_OVERLAP", 422)
ERR_TIMING_VIOLATION = ("ERR_TIMING_VIOLATION", 422)
# business constraint
ERR_CAPACITY_EXCEEDED = ("ERR_CAPACITY_EXCEEDED", 422)
ERR_DUPLICATE = ("ERR_DUPLICATE", 409)
ERR_DOCUMENTATION_STANDARD = ("ERR_DOCUMENTATION_STANDARD", 422)
ERR_INSUFFICIENT_CREDIBILITY = ("ERR_INSUFFICIENT_CREDIBILITY", 422)
ERR_CLOSURE_GATE = ("ERR_CLOSURE_GATE", 422)
ERR_REOPEN_LIMIT = ("ERR_REOPEN_LIMIT", 422)
# business referential
ERR_RECIPIENT_MISMATCH = ("ERR_RECIPIENT_MISMATCH", 422)
ERR_SCOPE_NOT_FOUND = ("ERR_SCOPE_NOT_FOUND", 422)
# business fiscal
ERR_TREND_HEADCOUNT_ZERO = ("ERR_TREND_HEADCOUNT_ZERO", 422)
# optimistic concurrency
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
# syntactic (final screen)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)


def raise_error(spec, message: str = ""):
    error_id, status = spec
    raise ApiError(error_id, status, message or error_id)
