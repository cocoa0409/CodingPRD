class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (id -> http status)
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_RESOURCE_OWNER = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_REFERENCED_NOT_FOUND = ("ERR_REFERENCED_NOT_FOUND", 404)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)
ERR_DUPLICATE_PRIMARY = ("ERR_DUPLICATE_PRIMARY", 409)
ERR_PLAN_AREA_MISMATCH = ("ERR_PLAN_AREA_MISMATCH", 409)
ERR_SEP_WINDOW_CLOSED = ("ERR_SEP_WINDOW_CLOSED", 409)
ERR_SEP_NOT_APPROVED = ("ERR_SEP_NOT_APPROVED", 409)
ERR_NO_BENCHMARK_PLAN = ("ERR_NO_BENCHMARK_PLAN", 409)
ERR_APTC_EXCEEDS_MAX = ("ERR_APTC_EXCEEDS_MAX", 409)
ERR_OVERLAPPING_COVERAGE = ("ERR_OVERLAPPING_COVERAGE", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)


def err(code_tuple, message=None):
    eid, status = code_tuple
    return ApiError(eid, status, message)
