"""Error catalog and the ApiError exception type.

Every error_id / http_status pair is taken verbatim from PRD §5 and
SCAFFOLD §1.6. Do not invent codes.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalog (PRD §5 / SCAFFOLD §1.6) ---------------------------------
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_NOT_RESOURCE_OWNER = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_FK_NOT_FOUND = ("ERR_FK_NOT_FOUND", 422)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_DEPENDENCY_NOT_READY = ("ERR_DEPENDENCY_NOT_READY", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_PADDLE_INELIGIBLE = ("ERR_PADDLE_INELIGIBLE", 409)
ERR_INVALID_LOT_TERMS = ("ERR_INVALID_LOT_TERMS", 422)
ERR_BID_TOO_LOW = ("ERR_BID_TOO_LOW", 409)
ERR_DUPLICATE = ("ERR_DUPLICATE", 409)
ERR_CREDIT_LIMIT_EXCEEDED = ("ERR_CREDIT_LIMIT_EXCEEDED", 409)
ERR_SALE_NOT_EMPTY_OF_OPEN_LOTS = ("ERR_SALE_NOT_EMPTY_OF_OPEN_LOTS", 409)
ERR_LOTS_REQUIRED = ("ERR_LOTS_REQUIRED", 409)
ERR_STATEMENT_ALREADY_PAID = ("ERR_STATEMENT_ALREADY_PAID", 409)
ERR_VALIDATION_PAGINATION = ("ERR_VALIDATION_PAGINATION", 400)


def err(catalog_entry, message=None):
    error_id, http_status = catalog_entry
    return ApiError(error_id, http_status, message)
