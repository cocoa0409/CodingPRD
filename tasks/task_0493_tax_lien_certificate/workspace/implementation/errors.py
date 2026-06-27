"""Error catalog (PRD §5 / scaffold §1.6).

Each entry maps an error_id to its HTTP status. The ApiError exception carries
the error_id, http_status, and a human-readable message; the global handler in
app.py renders it through the standard error envelope.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# (error_id, http_status) tuples — exact names/codes from the PRD error catalogue.
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_SEGREGATION_OF_DUTIES = ("ERR_SEGREGATION_OF_DUTIES", 403)
ERR_NOT_CERTIFICATE_HOLDER = ("ERR_NOT_CERTIFICATE_HOLDER", 403)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_INVALID_BID = ("ERR_INVALID_BID", 422)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_CROSS_COUNTY_REFERENCE = ("ERR_CROSS_COUNTY_REFERENCE", 409)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_SALE_NOT_DUE = ("ERR_SALE_NOT_DUE", 409)
ERR_SALE_EMPTY = ("ERR_SALE_EMPTY", 409)
ERR_REDEMPTION_PERIOD_OPEN = ("ERR_REDEMPTION_PERIOD_OPEN", 409)
ERR_DEED_ALREADY_AWARDED = ("ERR_DEED_ALREADY_AWARDED", 409)
ERR_BID_BELOW_MINIMUM = ("ERR_BID_BELOW_MINIMUM", 409)
ERR_DUPLICATE_SUB_TAX = ("ERR_DUPLICATE_SUB_TAX", 409)
ERR_INSUFFICIENT_ESCROW = ("ERR_INSUFFICIENT_ESCROW", 402)
ERR_VALIDATION = ("ERR_VALIDATION", 422)


def fail(err_tuple, message=None):
    error_id, http_status = err_tuple
    raise ApiError(error_id, http_status, message)
