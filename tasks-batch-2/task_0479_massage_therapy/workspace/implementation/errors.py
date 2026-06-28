"""Error definitions. Error IDs and HTTP statuses are normative (PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue (PRD §5)
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_UNAUTHORIZED = ("ERR_UNAUTHORIZED", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_CONSENT_REQUIRED = ("ERR_CONSENT_REQUIRED", 422)
ERR_CONTRAINDICATION = ("ERR_CONTRAINDICATION", 422)
ERR_INTAKE_INVALID = ("ERR_INTAKE_INVALID", 422)
ERR_LICENSE_EXPIRED = ("ERR_LICENSE_EXPIRED", 422)
ERR_CERTIFICATION_REQUIRED = ("ERR_CERTIFICATION_REQUIRED", 422)
ERR_TABLE_UNSUITABLE = ("ERR_TABLE_UNSUITABLE", 422)
ERR_TABLE_DOUBLE_BOOKED = ("ERR_TABLE_DOUBLE_BOOKED", 409)
ERR_THERAPIST_DOUBLE_BOOKED = ("ERR_THERAPIST_DOUBLE_BOOKED", 409)
ERR_NO_CREDITS = ("ERR_NO_CREDITS", 422)
ERR_INSUFFICIENT_HSA = ("ERR_INSUFFICIENT_HSA", 422)
ERR_NOT_BILLABLE = ("ERR_NOT_BILLABLE", 422)
ERR_RENEWAL_TOO_EARLY = ("ERR_RENEWAL_TOO_EARLY", 422)


def err(tup, message=None):
    """Build an ApiError from a (error_id, http_status) tuple."""
    return ApiError(tup[0], tup[1], message)
