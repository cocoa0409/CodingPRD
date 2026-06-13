"""Error catalog and the ApiError exception carrying error_id + http_status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (id -> http status) from PRD §5 / scaffold §1.6
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_RESOURCE_OWNER = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_VALIDATION = ("ERR_VALIDATION", 422)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_PATRON_BARRED = ("ERR_PATRON_BARRED", 403)
ERR_PROBATION_PRIME_BLOCKED = ("ERR_PROBATION_PRIME_BLOCKED", 403)
ERR_COI_REQUIRED = ("ERR_COI_REQUIRED", 422)
ERR_COI_INSUFFICIENT = ("ERR_COI_INSUFFICIENT", 422)
ERR_INVALID_WINDOW = ("ERR_INVALID_WINDOW", 422)
ERR_DOUBLE_BOOKING = ("ERR_DOUBLE_BOOKING", 409)
ERR_PAYMENT_REQUIRED = ("ERR_PAYMENT_REQUIRED", 422)
ERR_LOTTERY_NOT_CLOSED = ("ERR_LOTTERY_NOT_CLOSED", 409)
ERR_LOTTERY_NO_ENTRIES = ("ERR_LOTTERY_NO_ENTRIES", 409)
ERR_DUPLICATE_ENTRY = ("ERR_DUPLICATE_ENTRY", 409)
ERR_PAGINATION_INVALID = ("ERR_PAGINATION_INVALID", 422)


def err(catalog_entry, message=None):
    error_id, http_status = catalog_entry
    return ApiError(error_id, http_status, message)
