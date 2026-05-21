"""Domain error definitions for the Travel & Expense Reimbursement API."""


class APIError(Exception):
    """Raised to signal a structured error response."""

    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error helpers — every error_id matches the scaffold's error catalog.
def err_missing_auth(msg="Missing or malformed X-User-ID / X-User-Role headers."):
    return APIError("ERR_MISSING_AUTH", msg, 401)


def err_invalid_role(msg="X-User-Role is not recognized or does not match X-User-ID."):
    return APIError("ERR_INVALID_ROLE", msg, 401)


def err_not_found(msg="Resource not found."):
    return APIError("ERR_NOT_FOUND", msg, 404)


def err_reference_not_found(msg="Referenced resource does not exist."):
    return APIError("ERR_REFERENCE_NOT_FOUND", msg, 422)


def err_invalid_state(msg="Operation invalid for the resource's current state."):
    return APIError("ERR_INVALID_STATE", msg, 409)


def err_cross_entity_state(msg="Related entity is not in a permitted state."):
    return APIError("ERR_CROSS_ENTITY_STATE", msg, 409)


def err_segregation_of_duties(msg="Segregation-of-duties violation."):
    return APIError("ERR_SEGREGATION_OF_DUTIES", msg, 403)


def err_receipt_already_used(msg="Receipt is already bound to a different ExpenseLine."):
    return APIError("ERR_RECEIPT_ALREADY_USED", msg, 409)


def err_card_trip_mismatch(msg="VirtualCard.trip_id does not match the report's parent trip."):
    return APIError("ERR_CARD_TRIP_MISMATCH", msg, 422)


def err_expense_outside_trip_window(msg="expense_date is outside the trip window."):
    return APIError("ERR_EXPENSE_OUTSIDE_TRIP_WINDOW", msg, 422)


def err_per_diem_unavailable(msg="No PerDiemRate row covers the destination on the relevant date."):
    return APIError("ERR_PER_DIEM_UNAVAILABLE", msg, 422)


def err_receipt_required(msg="Receipt is required for this category or amount."):
    return APIError("ERR_RECEIPT_REQUIRED", msg, 422)


def err_category_field_missing(msg="Category-specific required field is missing."):
    return APIError("ERR_CATEGORY_FIELD_MISSING", msg, 422)


def err_card_limit_exceeds_budget(msg="VirtualCard.credit_limit_cents exceeds Trip.estimated_budget_cents."):
    return APIError("ERR_CARD_LIMIT_EXCEEDS_BUDGET", msg, 422)


def err_card_limit_exceeded(msg="VirtualCard authorization would exceed credit_limit_cents."):
    return APIError("ERR_CARD_LIMIT_EXCEEDED", msg, 409)


def err_oop_wrong_approver_role(msg="OOP approval step invoked by the wrong role."):
    return APIError("ERR_OOP_WRONG_APPROVER_ROLE", msg, 403)


def err_oop_duplicate_approver(msg="OOP final approver coincides with L1 approver."):
    return APIError("ERR_OOP_DUPLICATE_APPROVER", msg, 403)


def err_stale_version(msg="OCC version mismatch on PATCH."):
    return APIError("ERR_STALE_VERSION", msg, 409)


def err_report_already_claimed(msg="Report has already been claimed by another reviewer."):
    return APIError("ERR_REPORT_ALREADY_CLAIMED", msg, 409)


def err_validation(msg="Input validation failed."):
    return APIError("ERR_VALIDATION", msg, 400)
