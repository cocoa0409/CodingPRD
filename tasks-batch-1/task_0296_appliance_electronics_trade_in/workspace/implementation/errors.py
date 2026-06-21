"""Error classes and error-ID constants.

Every error_id and its HTTP status is taken verbatim from the scaffold's
error catalog (Table 6) and PRD Section 5.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Auth / structural
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_OWNER = ("ERR_NOT_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_FK_NOT_FOUND = ("ERR_FK_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)

# Business
ERR_MODEL_RETIRED = ("ERR_MODEL_RETIRED", 409)
ERR_PROMO_INVALID = ("ERR_PROMO_INVALID", 409)
ERR_UNKNOWN_DEFECT = ("ERR_UNKNOWN_DEFECT", 422)
ERR_QUOTE_EXPIRED = ("ERR_QUOTE_EXPIRED", 409)
ERR_DATA_WIPE_REQUIRED = ("ERR_DATA_WIPE_REQUIRED", 409)
ERR_DUPLICATE = ("ERR_DUPLICATE", 409)
ERR_INVALID_MULTIPLIERS = ("ERR_INVALID_MULTIPLIERS", 422)
ERR_PROMO_WINDOW_OVERLAP = ("ERR_PROMO_WINDOW_OVERLAP", 409)
ERR_SLOT_OVERLAP = ("ERR_SLOT_OVERLAP", 409)


def err(spec, message=None):
    """Build an ApiError from one of the (id, status) constants above."""
    error_id, http_status = spec
    return ApiError(error_id, http_status, message)
