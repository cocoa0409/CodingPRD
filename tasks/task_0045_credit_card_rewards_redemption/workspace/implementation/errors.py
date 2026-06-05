class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (id -> http status) per PRD §5 / SCAFFOLD §1.6
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_NOT_ACCOUNT_OWNER = ("ERR_NOT_ACCOUNT_OWNER", 403)
ERR_RESOURCE_NOT_FOUND = ("ERR_RESOURCE_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_PARTNER_FIELD_MISMATCH = ("ERR_PARTNER_FIELD_MISMATCH", 422)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_CROSS_PRODUCT_MISMATCH = ("ERR_CROSS_PRODUCT_MISMATCH", 422)
ERR_DUPLICATE_ACTIVATION = ("ERR_DUPLICATE_ACTIVATION", 409)
ERR_TEMPORAL_OUT_OF_RANGE = ("ERR_TEMPORAL_OUT_OF_RANGE", 422)
ERR_BELOW_MIN_TRANSFER = ("ERR_BELOW_MIN_TRANSFER", 422)
ERR_STALE_ACCOUNT_VERSION = ("ERR_STALE_ACCOUNT_VERSION", 412)
ERR_INSUFFICIENT_POINTS = ("ERR_INSUFFICIENT_POINTS", 422)


def err(code_tuple, message=None):
    eid, status = code_tuple
    return ApiError(eid, status, message)
