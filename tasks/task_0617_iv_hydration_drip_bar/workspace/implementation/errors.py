"""Error catalogue (PRD §5) and the ApiError exception class."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue: error_id -> http status (PRD §5 / scaffold §1.6)
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_SCREENING_BLOCKED = ("ERR_SCREENING_BLOCKED", 409)
ERR_CONSENT_MISSING = ("ERR_CONSENT_MISSING", 409)
ERR_SEGREGATION_OF_DUTIES = ("ERR_SEGREGATION_OF_DUTIES", 409)
ERR_NO_STANDING_ORDER = ("ERR_NO_STANDING_ORDER", 409)
ERR_SLOT_CONFLICT = ("ERR_SLOT_CONFLICT", 409)
ERR_SUPPLY_UNAVAILABLE = ("ERR_SUPPLY_UNAVAILABLE", 409)
ERR_CREDIT_INSUFFICIENT = ("ERR_CREDIT_INSUFFICIENT", 409)
ERR_LOT_HAS_RESERVATIONS = ("ERR_LOT_HAS_RESERVATIONS", 409)
ERR_CONSENT_NOT_AFFIRMED = ("ERR_CONSENT_NOT_AFFIRMED", 422)
ERR_ROUTE_LOCKED = ("ERR_ROUTE_LOCKED", 409)
ERR_VALIDATION_PARAM = ("ERR_VALIDATION_PARAM", 400)


def err(catalog_entry, message=None):
    error_id, http_status = catalog_entry
    return ApiError(error_id, http_status, message)
