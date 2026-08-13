"""API error type carrying the scaffold-defined error_id and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


# ---- auth / request shape ----
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_UNAUTHORIZED = ("ERR_UNAUTHORIZED", 403)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)

# ---- state (409) ----
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_UNIT_NOT_AVAILABLE = ("ERR_UNIT_NOT_AVAILABLE", 409)
ERR_RENTAL_WINDOW_OVERLAP = ("ERR_RENTAL_WINDOW_OVERLAP", 409)
ERR_DISPATCH_WINDOW_OVERLAP = ("ERR_DISPATCH_WINDOW_OVERLAP", 409)
ERR_INSPECTION_NOT_APPROVED = ("ERR_INSPECTION_NOT_APPROVED", 409)

# ---- OCC (412) ----
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)

# ---- business (422) ----
ERR_PM_OVERDUE = ("ERR_PM_OVERDUE", 422)
ERR_NO_CERTIFIED_OPERATOR = ("ERR_NO_CERTIFIED_OPERATOR", 422)
ERR_OPERATOR_CERT_EXPIRED = ("ERR_OPERATOR_CERT_EXPIRED", 422)
ERR_UNIT_DISPOSITION_MISMATCH = ("ERR_UNIT_DISPOSITION_MISMATCH", 422)
ERR_TECHNICIAN_INACTIVE = ("ERR_TECHNICIAN_INACTIVE", 422)
ERR_QUOTE_EMPTY = ("ERR_QUOTE_EMPTY", 422)
ERR_VAN_STOCK_INSUFFICIENT = ("ERR_VAN_STOCK_INSUFFICIENT", 422)
ERR_FUEL_PROGRAM_MISMATCH = ("ERR_FUEL_PROGRAM_MISMATCH", 422)
ERR_HOUR_METER_REGRESSION = ("ERR_HOUR_METER_REGRESSION", 422)
ERR_QUOTE_EXPIRED = ("ERR_QUOTE_EXPIRED", 422)
ERR_ACCOUNT_CREDIT_HOLD = ("ERR_ACCOUNT_CREDIT_HOLD", 422)
ERR_CREDIT_LIMIT_EXCEEDED = ("ERR_CREDIT_LIMIT_EXCEEDED", 422)
# PRD §3.2 names this error verbatim on the quote-accept ladder, between the
# expiry check and the credit check; §5 does not catalogue a status for it.
# 422 chosen to match the sibling accept-gate errors in the same sentence.
ERR_UNIT_NOT_LISTED = ("ERR_UNIT_NOT_LISTED", 422)


def raise_err(spec, message):
    raise ApiError(spec[0], spec[1], message)
