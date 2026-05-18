"""Custom error type carrying error_id, message and HTTP status (scaffold §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Auth / authorization (priority 1-5)
def err_missing_auth(msg="Authentication headers missing or empty."):
    return ApiError("ERR_MISSING_AUTH", 401, msg)


def err_unknown_role(msg="X-User-Role is not a recognized role."):
    return ApiError("ERR_UNKNOWN_ROLE", 401, msg)


def err_forbidden(msg="Acting role is not permitted for this endpoint."):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def err_segregation(msg="Segregation of duties: Originator may not perform Servicer-only operations."):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


# Existence (priority 6-7)
def err_not_found(msg="Resource not found."):
    return ApiError("ERR_RESOURCE_NOT_FOUND", 404, msg)


# State (priority 10-18)
def err_invalid_state(msg="Operation not allowed in current state."):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_heloc_defaulted(msg="Operation not allowed on a HELOC in DEFAULT."):
    return ApiError("ERR_HELOC_DEFAULTED", 409, msg)


def err_heloc_closed(msg="HELOC is CLOSED; mutation not allowed."):
    return ApiError("ERR_HELOC_CLOSED", 409, msg)


def err_draw_period_ended(msg="Draw period has ended; no further draws permitted."):
    return ApiError("ERR_DRAW_PERIOD_ENDED", 409, msg)


def err_already_bankrupt(msg="Borrower is already flagged bankrupt."):
    return ApiError("ERR_ALREADY_BANKRUPT", 409, msg)


def err_version_conflict(msg="Supplied version does not match current Heloc.version."):
    return ApiError("ERR_VERSION_CONFLICT", 409, msg)


# Business safety (priority 20-23, 26)
def err_occupancy_not_primary(msg="Property occupancy must be PRIMARY."):
    return ApiError("ERR_OCCUPANCY_NOT_PRIMARY", 422, msg)


def err_no_senior_lien(msg="Property has no CURRENT senior lien."):
    return ApiError("ERR_NO_SENIOR_LIEN", 422, msg)


def err_borrower_bankrupt(msg="Borrower is flagged bankrupt."):
    return ApiError("ERR_BORROWER_BANKRUPT", 422, msg)


def err_cltv_exceeded(msg="Combined loan-to-value exceeds 100%."):
    return ApiError("ERR_CLTV_EXCEEDED", 422, msg)


def err_borrower_property_mismatch(msg="Property's borrower_id does not match Heloc.borrower_id."):
    return ApiError("ERR_BORROWER_PROPERTY_MISMATCH", 422, msg)


# Business temporal (priority 24)
def err_payment_below_minimum(msg="Payment amount is less than minimum payment due."):
    return ApiError("ERR_PAYMENT_BELOW_MINIMUM", 422, msg)


# Business fiscal (priority 30-32)
def err_insufficient_credit(msg="Draw exceeds available credit."):
    return ApiError("ERR_INSUFFICIENT_AVAILABLE_CREDIT", 422, msg)


def err_balance_not_zero(msg="Cannot close: principal or accrued interest is non-zero."):
    return ApiError("ERR_BALANCE_NOT_ZERO", 422, msg)


def err_rate_bound_invalid(msg="Rate-configuration bounds are inconsistent."):
    return ApiError("ERR_RATE_BOUND_INVALID", 422, msg)


# Field-shape (catch-all body validation)
def err_validation_failed(msg="Field-shape validation failed."):
    return ApiError("ERR_VALIDATION_FAILED", 400, msg)
