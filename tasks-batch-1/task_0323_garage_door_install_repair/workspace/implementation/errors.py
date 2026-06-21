"""Error classes and error ID constants (SCAFFOLD §1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue — exact IDs and HTTP codes from PRD §5 / SCAFFOLD §1.6
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)
ERR_DUPLICATE = ("ERR_DUPLICATE", 409)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_QUOTE_EXPIRED = ("ERR_QUOTE_EXPIRED", 409)
ERR_SAFETY_NOT_PASSED = ("ERR_SAFETY_NOT_PASSED", 409)
ERR_PARTS_NOT_CONSUMED = ("ERR_PARTS_NOT_CONSUMED", 409)
ERR_TECH_NOT_ELIGIBLE = ("ERR_TECH_NOT_ELIGIBLE", 409)
ERR_TECH_SCHEDULE_CONFLICT = ("ERR_TECH_SCHEDULE_CONFLICT", 409)
ERR_EQUIPMENT_UNAVAILABLE = ("ERR_EQUIPMENT_UNAVAILABLE", 409)
ERR_INSUFFICIENT_STOCK = ("ERR_INSUFFICIENT_STOCK", 409)
ERR_CUSTOMER_BLOCKED = ("ERR_CUSTOMER_BLOCKED", 409)
ERR_TUNEUPS_EXHAUSTED = ("ERR_TUNEUPS_EXHAUSTED", 409)
ERR_FINANCING_CEILING = ("ERR_FINANCING_CEILING", 409)
ERR_SEGREGATION_VIOLATION = ("ERR_SEGREGATION_VIOLATION", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)


def err(spec, message=""):
    """Build an ApiError from a (error_id, http_status) tuple."""
    return ApiError(spec[0], spec[1], message)
