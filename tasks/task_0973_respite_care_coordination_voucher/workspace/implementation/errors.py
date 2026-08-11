"""Error classes with the exact error_id catalog from the scaffold."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(msg="Missing or invalid X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_unauthorized_role(msg="Role not authorized for this endpoint"):
    return ApiError("ERR_UNAUTHORIZED_ROLE", 403, msg)


def err_forbidden_ownership(msg="Entity-backed actor does not own the target resource"):
    return ApiError("ERR_FORBIDDEN_OWNERSHIP", 403, msg)


def err_invalid_request(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


NOT_FOUND_IDS = {
    "program": "ERR_PROGRAM_NOT_FOUND",
    "caregiver": "ERR_CAREGIVER_NOT_FOUND",
    "application": "ERR_APPLICATION_NOT_FOUND",
    "allocation": "ERR_ALLOCATION_NOT_FOUND",
    "voucher": "ERR_VOUCHER_NOT_FOUND",
    "provider": "ERR_PROVIDER_NOT_FOUND",
    "window": "ERR_WINDOW_NOT_FOUND",
    "booking": "ERR_BOOKING_NOT_FOUND",
    "visit": "ERR_VISIT_NOT_FOUND",
    "claim": "ERR_CLAIM_NOT_FOUND",
    "emergency": "ERR_EMERGENCY_NOT_FOUND",
    "snapshot": "ERR_SNAPSHOT_NOT_FOUND",
}


def err_not_found(kind, msg=None):
    return ApiError(NOT_FOUND_IDS[kind], 404, msg or f"Referenced {kind} id does not exist")


def err_posture_gate(msg="Program posture forbids the operation"):
    return ApiError("ERR_POSTURE_GATE", 409, msg)


def err_invalid_state(msg="State machine rejects the transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_caregiver_not_active(msg="Caregiver not ACTIVE"):
    return ApiError("ERR_CAREGIVER_NOT_ACTIVE", 422, msg)


def err_redetermination_overdue(msg="Caregiver in REDETERMINATION_PENDING cannot receive new vouchers"):
    return ApiError("ERR_REDETERMINATION_OVERDUE", 422, msg)


def err_provider_not_active(msg="Provider credential_status not ACTIVE"):
    return ApiError("ERR_PROVIDER_NOT_ACTIVE", 422, msg)


def err_allocation_caregiver_mismatch(msg="Allocation does not belong to caregiver or is not OPEN"):
    return ApiError("ERR_ALLOCATION_CAREGIVER_MISMATCH", 422, msg)


def err_duplicate_email(msg="Caregiver email already registered"):
    return ApiError("ERR_DUPLICATE_EMAIL", 409, msg)


def err_window_overlap(msg="New availability window overlaps an existing window"):
    return ApiError("ERR_WINDOW_OVERLAP", 409, msg)


def err_window_capacity_full(msg="Booking would raise window overlap count above capacity"):
    return ApiError("ERR_WINDOW_CAPACITY_FULL", 409, msg)


def err_caregiver_double_booked(msg="New booking violates the 30-minute caregiver buffer"):
    return ApiError("ERR_CAREGIVER_DOUBLE_BOOKED", 409, msg)


def err_duplicate_survey(msg="A satisfaction survey already exists for the booking"):
    return ApiError("ERR_DUPLICATE_SURVEY", 409, msg)


def err_voucher_not_issuable(msg="Voucher not ISSUED or lacks unconsumed hours"):
    return ApiError("ERR_VOUCHER_NOT_ISSUABLE", 422, msg)


def err_booking_beyond_voucher_expiry(msg="Booking end_at is after voucher.expires_at"):
    return ApiError("ERR_BOOKING_BEYOND_VOUCHER_EXPIRY", 422, msg)


def err_booking_not_confirmed(msg="Check-in attempted on a booking not in CONFIRMED status"):
    return ApiError("ERR_BOOKING_NOT_CONFIRMED", 409, msg)


def err_evv_outside_window(msg="Check-in outside [start_at - 15 minutes, end_at]"):
    return ApiError("ERR_EVV_OUTSIDE_WINDOW", 422, msg)


def err_evv_already_open(msg="An OPEN visit record already exists for the booking"):
    return ApiError("ERR_EVV_ALREADY_OPEN", 409, msg)


def err_appeal_window_closed(msg="Appeal attempted after appeal window"):
    return ApiError("ERR_APPEAL_WINDOW_CLOSED", 422, msg)


def err_emergency_window_past(msg="Emergency needed_start_at is not in the future"):
    return ApiError("ERR_EMERGENCY_WINDOW_PAST", 422, msg)


def err_insufficient_hours(msg="Voucher authorized_hours exceeds allocation.available_hours"):
    return ApiError("ERR_INSUFFICIENT_HOURS", 422, msg)


def err_quarterly_cap(msg="Quarterly cap exceeded"):
    return ApiError("ERR_QUARTERLY_CAP_EXCEEDED", 422, msg)


def err_annual_cap(msg="Annual cap exceeded"):
    return ApiError("ERR_ANNUAL_CAP_EXCEEDED", 422, msg)


def err_budget_exceeded(msg="Provisional encumbrance exceeds unencumbered program budget"):
    return ApiError("ERR_BUDGET_EXCEEDED", 422, msg)


def err_emergency_reserve_exhausted(msg="Triage approved_hours exceeds remaining emergency reserve"):
    return ApiError("ERR_EMERGENCY_RESERVE_EXHAUSTED", 422, msg)


def err_no_provider_available(msg="Selector pool empty"):
    return ApiError("ERR_NO_PROVIDER_AVAILABLE", 422, msg)


def err_stale_version(msg="expected version does not match the parent entity's current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)
