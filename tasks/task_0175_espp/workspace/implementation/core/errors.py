"""Domain error definitions for the ESPP API."""


class APIError(Exception):
    """Raised to signal a structured error response."""

    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error helpers — every error_id matches the scaffold's error catalog.
def err_auth_required(msg="Missing or empty X-User-ID / X-User-Role header."):
    return APIError("ERR_AUTH_REQUIRED", msg, 401)


def err_auth_invalid_role(msg="X-User-Role is not recognized."):
    return APIError("ERR_AUTH_INVALID_ROLE", msg, 401)


def err_forbidden(msg="Role not permitted for the requested operation."):
    return APIError("ERR_FORBIDDEN", msg, 403)


def err_not_found(msg="Resource not found."):
    return APIError("ERR_NOT_FOUND", msg, 404)


def err_not_owner(msg="Acting participant is not the owner of the referenced resource."):
    return APIError("ERR_NOT_OWNER", msg, 403)


def err_plan_not_active(msg="Plan is not ACTIVE."):
    return APIError("ERR_PLAN_NOT_ACTIVE", msg, 409)


def err_period_not_open(msg="OfferingPeriod is not in the required state for this operation."):
    return APIError("ERR_PERIOD_NOT_OPEN", msg, 409)


def err_invalid_period_state(msg="OfferingPeriod is not in a valid state for this operation."):
    return APIError("ERR_INVALID_PERIOD_STATE", msg, 409)


def err_invalid_enrollment_state(msg="Enrollment is not in ACTIVE state."):
    return APIError("ERR_INVALID_ENROLLMENT_STATE", msg, 409)


def err_invalid_disposition_state(msg="Disposition is not in REPORTED/AMENDED state."):
    return APIError("ERR_INVALID_DISPOSITION_STATE", msg, 409)


def err_duplicate_enrollment(msg="An enrollment already exists for this participant on this period."):
    return APIError("ERR_DUPLICATE_ENROLLMENT", msg, 409)


def err_duplicate_plan_name(msg="Plan.name is not unique."):
    return APIError("ERR_DUPLICATE_PLAN_NAME", msg, 409)


def err_period_length_out_of_range(msg="offering_period_months must be in [6, 24]."):
    return APIError("ERR_PERIOD_LENGTH_OUT_OF_RANGE", msg, 422)


def err_contribution_rate_out_of_range(msg="contribution_rate_bp out of allowed range."):
    return APIError("ERR_CONTRIBUTION_RATE_OUT_OF_RANGE", msg, 422)


def err_annual_accrual_cap_exceeded(msg="Annual accrual cap would be exceeded."):
    return APIError("ERR_ANNUAL_ACCRUAL_CAP_EXCEEDED", msg, 422)


def err_fmv_before_period_end(msg="purchase_date_fmv_cents cannot be set before the period end."):
    return APIError("ERR_FMV_BEFORE_PERIOD_END", msg, 409)


def err_grant_fmv_window(msg="grant_date_fmv_cents may only be set on the start_date day and if not yet set."):
    return APIError("ERR_GRANT_FMV_WINDOW", msg, 409)


def err_disposition_date_out_of_range(msg="disposition_date is outside the valid window."):
    return APIError("ERR_DISPOSITION_DATE_OUT_OF_RANGE", msg, 422)


def err_shares_exceed_balance(msg="shares_disposed exceeds remaining undisposed shares."):
    return APIError("ERR_SHARES_EXCEED_BALANCE", msg, 422)


def err_form_3922_immutable(msg="Form 3922 is immutable."):
    return APIError("ERR_FORM_3922_IMMUTABLE", msg, 409)


def err_sod_violation(msg="Segregation-of-duties violation: same X-User-ID posted contributions and now attempts run-purchase."):
    return APIError("ERR_SOD_VIOLATION", msg, 403)


def err_version_conflict(msg="version does not match stored row version."):
    return APIError("ERR_VERSION_CONFLICT", msg, 409)


def err_pagination_invalid(msg="limit or offset outside allowed bounds."):
    return APIError("ERR_PAGINATION_INVALID", msg, 422)


def err_clock_not_advancing(msg="to_timestamp must be strictly greater than current_time."):
    return APIError("ERR_CLOCK_NOT_ADVANCING", msg, 422)
