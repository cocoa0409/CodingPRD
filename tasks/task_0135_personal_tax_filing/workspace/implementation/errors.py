"""Custom error type carrying error_id, http_status, and message."""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ── Quick constructors mirroring SCAFFOLD §1.6 error catalogue ────────────


def err_auth_required(msg="Authentication headers missing."):
    return ApiError("ERR_AUTH_REQUIRED", 401, msg)


def err_forbidden(msg="Acting role is not permitted for this endpoint."):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def err_taxpayer_not_found(msg="Taxpayer not found."):
    return ApiError("ERR_TAXPAYER_NOT_FOUND", 404, msg)


def err_return_not_found(msg="TaxReturn not found."):
    return ApiError("ERR_RETURN_NOT_FOUND", 404, msg)


def err_resource_not_found(msg="Resource not found."):
    return ApiError("ERR_RESOURCE_NOT_FOUND", 404, msg)


def err_taxpayer_locked(msg="Taxpayer is locked."):
    return ApiError("ERR_TAXPAYER_LOCKED", 409, msg)


def err_invalid_state(msg="Operation not permitted in current state."):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_amendment_not_allowed(msg="Original return is not ACCEPTED."):
    return ApiError("ERR_AMENDMENT_NOT_ALLOWED", 409, msg)


def err_amendment_already_open(msg="An active amendment already exists for this return."):
    return ApiError("ERR_AMENDMENT_ALREADY_OPEN", 409, msg)


def err_qualified_div_exceeds_ordinary(msg="qualified_dividends_cents cannot exceed ordinary_dividends_cents."):
    return ApiError("ERR_QUALIFIED_DIV_EXCEEDS_ORDINARY", 422, msg)


def err_income_doc_invalid(msg="Income document inputs are invalid."):
    return ApiError("ERR_INCOME_DOC_INVALID", 422, msg)


def err_salt_cap_exceeded(msg="Schedule A SALT input exceeds $10,000 cap."):
    return ApiError("ERR_SALT_CAP_EXCEEDED", 422, msg)


def err_qualifying_children_exceed(msg="qualifying_children_under_17 exceeds dependents_count."):
    return ApiError("ERR_QUALIFYING_CHILDREN_EXCEED_DEPENDENTS", 422, msg)


def err_credit_ineligible(msg="Credit is ineligible based on inputs."):
    return ApiError("ERR_CREDIT_INELIGIBLE", 422, msg)


def err_duplicate_credit(msg="Credit of this type already exists on this return."):
    return ApiError("ERR_DUPLICATE_CREDIT", 409, msg)


def err_duplicate_schedule(msg="Schedule of this type already exists on this return."):
    return ApiError("ERR_DUPLICATE_SCHEDULE", 409, msg)


def err_duplicate_return(msg="A non-DRAFT return already exists for this (taxpayer_id, tax_year)."):
    return ApiError("ERR_DUPLICATE_RETURN", 409, msg)


def err_payment_date_past(msg="scheduled_pay_date must be strictly after current clock value."):
    return ApiError("ERR_PAYMENT_DATE_PAST", 422, msg)


def err_payment_cannot_cancel(msg="Payment cannot be cancelled on or after its scheduled_pay_date."):
    return ApiError("ERR_PAYMENT_CANNOT_CANCEL", 409, msg)


def err_version_conflict(msg="Version mismatch on optimistic concurrency check."):
    return ApiError("ERR_VERSION_CONFLICT", 409, msg)


def err_invalid_input(msg="Required field missing, malformed, or out of supported range."):
    return ApiError("ERR_INVALID_INPUT", 422, msg)
