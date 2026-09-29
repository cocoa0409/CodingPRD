"""Error catalogue and the single API exception type."""

ERROR_STATUS = {
    # ---- auth ----
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_DEALER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_UNAUTHORIZED_FOR_ESCALATED_GOODWILL": 403,
    # ---- existence ----
    "ERR_STATE_LAW_PROFILE_NOT_FOUND": 404,
    "ERR_DEALER_NOT_FOUND": 404,
    "ERR_VEHICLE_NOT_FOUND": 404,
    "ERR_LABOR_OPERATION_NOT_FOUND": 404,
    "ERR_CATALOG_ITEM_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_LABOR_RATE_REQUEST_NOT_FOUND": 404,
    "ERR_PARTS_RETURN_NOT_FOUND": 404,
    "ERR_AUDIT_NOT_FOUND": 404,
    "ERR_FINDING_NOT_FOUND": 404,
    "ERR_APPEAL_NOT_FOUND": 404,
    "ERR_GOODWILL_AUTH_NOT_FOUND": 404,
    # ---- concurrency ----
    "ERR_STALE_DEALER_VERSION": 412,
    "ERR_STALE_CLAIM_VERSION": 412,
    "ERR_STALE_AUDIT_VERSION": 412,
    # ---- state ----
    "ERR_CLAIM_NOT_ADJUDICABLE": 409,
    "ERR_CLAIM_STILL_SUSPENDED": 409,
    "ERR_CLAIM_NOT_RESUBMITTABLE": 409,
    "ERR_CLAIM_NOT_PAYABLE": 409,
    "ERR_CLAIM_NOT_VOIDABLE": 409,
    "ERR_LABOR_RATE_REQUEST_INVALID_STATE": 409,
    "ERR_PARTS_RETURN_INVALID_STATE": 409,
    "ERR_AUDIT_INVALID_STATE": 409,
    "ERR_APPEAL_INVALID_STATE": 409,
    "ERR_GOODWILL_INVALID_STATE": 409,
    # ---- business ----
    "ERR_DEALER_SUSPENDED": 409,
    "ERR_DEALER_UNDER_AUDIT_HOLD": 409,
    "ERR_APPEAL_PENDING": 409,
    "ERR_PARTS_RETURN_OVERDUE": 409,
    "ERR_DUPLICATE_REPAIR_ORDER": 409,
    "ERR_OVERLAPPING_REPAIR_CLAIM": 409,
    "ERR_AUDIT_PERIOD_OVERLAP": 409,
    "ERR_APPEAL_WINDOW_CLOSED": 409,
    "ERR_FINDING_NOT_IN_AUDIT": 409,
    "ERR_CLAIM_NOT_ELIGIBLE_FOR_FINDING": 409,
    "ERR_NO_COVERAGE_WITHOUT_GOODWILL": 409,
    # ---- shape / fiscal ----
    "ERR_VALIDATION": 422,
    "ERR_NARRATIVE_INCOMPLETE": 422,
    "ERR_CAUSAL_PART_REQUIRED": 422,
    "ERR_INSUFFICIENT_RATE_SAMPLE": 422,
    "ERR_LABOR_TIME_EXCEEDS_MAX": 422,
    "ERR_LABOR_RATE_ABOVE_STATUTORY_CEILING": 422,
    "ERR_MARKUP_ABOVE_STATE_CAP": 422,
    "ERR_GOODWILL_LIMIT_EXCEEDED": 422,
}


class ApiError(Exception):
    """Raised anywhere in a handler; converted to the error envelope by app.py."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
