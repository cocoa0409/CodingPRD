"""Error catalog and the APIError exception.

Every error_id / http_status pair below is taken verbatim from the PRD §5
error catalogue and SCAFFOLD §1.6.
"""


class APIError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Auth / structural
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_VALIDATION = ("ERR_VALIDATION", 400)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)

# Business
ERR_BEDROOM_MISMATCH = ("ERR_BEDROOM_MISMATCH", 422)
ERR_VOUCHER_EXPIRED = ("ERR_VOUCHER_EXPIRED", 422)
ERR_INSPECTION_NOT_PASSED = ("ERR_INSPECTION_NOT_PASSED", 422)
ERR_RENT_NOT_REASONABLE = ("ERR_RENT_NOT_REASONABLE", 422)
ERR_RENT_BURDEN_EXCEEDED = ("ERR_RENT_BURDEN_EXCEEDED", 422)
ERR_PAYMENT_STANDARD_OUT_OF_BAND = ("ERR_PAYMENT_STANDARD_OUT_OF_BAND", 422)
ERR_SAME_REGION_PORT = ("ERR_SAME_REGION_PORT", 422)
ERR_CURE_DEADLINE_PASSED = ("ERR_CURE_DEADLINE_PASSED", 422)
ERR_NOT_MOBILITY_AREA = ("ERR_NOT_MOBILITY_AREA", 422)
ERR_DUPLICATE_PAYMENT_STANDARD = ("ERR_DUPLICATE_PAYMENT_STANDARD", 409)
ERR_HOUSEHOLD_NOT_ELIGIBLE = ("ERR_HOUSEHOLD_NOT_ELIGIBLE", 422)
ERR_VOUCHER_NOT_AVAILABLE = ("ERR_VOUCHER_NOT_AVAILABLE", 422)


def fail(catalog_entry, message):
    error_id, http_status = catalog_entry
    raise APIError(error_id, message, http_status)
