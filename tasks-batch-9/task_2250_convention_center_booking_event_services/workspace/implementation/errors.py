"""Error catalogue for the Convention Center Booking & Event Services API.

Every error_id and its HTTP status comes straight from PRD.md section 5
(Error Code Catalogue) and SCAFFOLD.yaml `errors`.
"""

ERROR_STATUS = {
    # --- auth ---
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- existence ---
    "ERR_CLIENT_NOT_FOUND": 404,
    "ERR_SPACE_NOT_FOUND": 404,
    "ERR_POLICY_WINDOW_NOT_FOUND": 404,
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_HOLD_NOT_FOUND": 404,
    "ERR_LICENSE_NOT_FOUND": 404,
    "ERR_VENDOR_NOT_FOUND": 404,
    "ERR_JURISDICTION_NOT_FOUND": 404,
    "ERR_SERVICE_ORDER_NOT_FOUND": 404,
    "ERR_LABOR_CALL_NOT_FOUND": 404,
    "ERR_CATERING_NOT_FOUND": 404,
    "ERR_SETTLEMENT_NOT_FOUND": 404,
    "ERR_BLACKOUT_NOT_FOUND": 404,
    # --- request validity ---
    "ERR_INVALID_REQUEST": 400,
    # --- booking qualification ---
    "ERR_POLICY_WINDOW_MISSING": 422,
    "ERR_CITYWIDE_QUALIFICATION_NOT_MET": 422,
    # --- state ---
    "ERR_BOOKING_STATE_INVALID": 409,
    "ERR_HOLD_STATE_INVALID": 409,
    "ERR_LICENSE_STATE_INVALID": 409,
    "ERR_SERVICE_ORDER_STATE_INVALID": 409,
    "ERR_LABOR_CALL_STATE_INVALID": 409,
    "ERR_CATERING_STATE_INVALID": 409,
    "ERR_SETTLEMENT_STATE_INVALID": 409,
    "ERR_BLACKOUT_STATE_INVALID": 409,
    "ERR_ORDER_POSTURE_NOT_OPEN": 409,
    # --- optimistic concurrency ---
    "ERR_STALE_LICENSE_VERSION": 412,
    "ERR_STALE_BOOKING_VERSION": 412,
    # --- uniqueness ---
    "ERR_POLICY_WINDOW_EXISTS": 409,
    "ERR_LICENSE_ALREADY_EXISTS": 409,
    "ERR_SETTLEMENT_ALREADY_EXISTS": 409,
    "ERR_CATERING_ALREADY_EXISTS": 409,
    "ERR_USAGE_RECORD_DUPLICATE": 409,
    # --- vendor / union eligibility ---
    "ERR_VENDOR_COI_EXPIRED": 422,
    "ERR_UNION_LOCKOUT": 422,
    "ERR_SPACE_NOT_RIGGING_CAPABLE": 422,
    "ERR_UNION_JURISDICTION_MISMATCH": 422,
    "ERR_VENDOR_CATEGORY_MISMATCH": 422,
    "ERR_EXCLUSIVE_VENDOR_REQUIRED": 422,
    "ERR_CATERING_EXCLUSIVITY_VIOLATION": 422,
    "ERR_OUTSIDE_CATERING_REASON_REQUIRED": 422,
    # --- temporal ---
    "ERR_BOOKING_WINDOW_CLOSED": 422,
    "ERR_MAINTENANCE_BLACKOUT_CONFLICT": 409,
    "ERR_SPACE_DATE_CONFLICT": 409,
    "ERR_RELEASE_DEADLINE_PASSED": 409,
    "ERR_CHALLENGE_DEADLINE_PASSED": 409,
    "ERR_MOVE_IN_NOT_REACHED": 409,
    "ERR_EVENT_NOT_ENDED": 409,
    "ERR_DISPUTE_WINDOW_CLOSED": 409,
    "ERR_DISPUTE_WINDOW_OPEN": 409,
    "ERR_WORK_DATE_OUTSIDE_EVENT": 422,
    # --- capacity and round limits ---
    "ERR_HOLD_LIMIT_REACHED": 409,
    "ERR_CHALLENGE_NOT_PERMITTED": 422,
    "ERR_CHALLENGE_LIMIT_REACHED": 409,
    "ERR_AMENDMENT_LIMIT_REACHED": 409,
    "ERR_SETTLEMENT_REVISION_LIMIT_REACHED": 409,
    "ERR_HOLD_NOT_FIRST_OPTION": 409,
    "ERR_UNION_CREW_OVERCOMMITTED": 409,
    # --- settlement composition ---
    "ERR_NO_USAGE_RECORDS": 422,
    "ERR_RENTAL_LINE_MISMATCH": 422,
    "ERR_SERVICE_ORDERS_NOT_RECONCILED": 409,
    # --- fiscal ---
    "ERR_INSUFFICIENT_DEPOSIT_CREDIT": 402,
    "ERR_CLIENT_HOLD_RESTRICTED": 409,
    "ERR_LINE_AMOUNT_INVALID": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and the role must be recognized.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorized for this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The acting licensee does not own the target resource.",
    "ERR_SEGREGATION_OF_DUTIES": "The finalizing user must differ from the issuing user.",
    "ERR_INVALID_REQUEST": "The request body or query parameters are invalid.",
}


class ApiError(Exception):
    """An error that maps to one entry of the PRD error catalogue."""

    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )
        super().__init__(self.message)


def err(error_id, message=None):
    """Build (do not raise) an ApiError. Callers use `raise err(...)`."""
    return ApiError(error_id, message)
