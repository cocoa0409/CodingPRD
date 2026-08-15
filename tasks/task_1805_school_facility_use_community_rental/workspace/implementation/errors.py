"""Error catalogue — ids and HTTP statuses from SCAFFOLD §1.6 / PRD §5."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def missing_context(msg="X-User-ID or X-User-Role header missing or malformed"):
    return ApiError("ERR_MISSING_OR_INVALID_CONTEXT_HEADER", 400, msg)


def invalid_request(msg="Malformed body, missing required field, wrong type, or enum outside declared set"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def forbidden(msg="Role not permitted for this endpoint or entity-backed role does not own the path resource"):
    return ApiError("ERR_FORBIDDEN_FOR_ROLE", 403, msg)


def segregation(msg="Adjudicate/resolve_appeal attempted by the operator who recorded the assessment intake"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


def not_found(msg="Path id does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_state(msg="Current lifecycle/financial state does not permit the requested action"):
    return ApiError("ERR_INVALID_STATE_TRANSITION", 409, msg)


def stale_version(msg="expected version does not match the entity's current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def capacity_exceeded(msg="headcount_estimate exceeds Facility.capacity"):
    return ApiError("ERR_CAPACITY_EXCEEDED", 422, msg)


def insurance_insufficient(msg="No VALID certificate covering the full event window with limits meeting the headcount tier"):
    return ApiError("ERR_INSURANCE_INSUFFICIENT", 422, msg)


def invalid_time_window(msg="Invalid time window (shape, duration, future start, seasonal span, or buffer multiple)"):
    return ApiError("ERR_INVALID_TIME_WINDOW", 422, msg)


def schedule_conflict(msg="Requested interval overlaps a SCHEDULED calendar event or an ISSUED/ACTIVE permit's blocked interval"):
    return ApiError("ERR_SCHEDULE_CONFLICT", 409, msg)


def reference_invalid(msg="Referenced facility/site/policy/series invalid"):
    return ApiError("ERR_REFERENCE_INVALID", 422, msg)


def renter_not_good_standing(msg="Renter org is SUSPENDED or BARRED"):
    return ApiError("ERR_RENTER_NOT_IN_GOOD_STANDING", 402, msg)


def payment_amount_mismatch(msg="DEPOSIT_CAPTURE amount != deposit_required_cents exactly"):
    return ApiError("ERR_PAYMENT_AMOUNT_MISMATCH", 402, msg)


def overpayment(msg="FEE_PAYMENT exceeds invoice remaining balance"):
    return ApiError("ERR_OVERPAYMENT", 402, msg)


def duplicate(msg="Uniqueness violation"):
    return ApiError("ERR_DUPLICATE", 409, msg)


def idempotency_conflict(msg="Idempotency key reused with a different payload"):
    return ApiError("ERR_IDEMPOTENCY_CONFLICT", 409, msg)


def revision_limit(msg="request_revision attempted when revision_round == 3"):
    return ApiError("ERR_REVISION_LIMIT_EXCEEDED", 409, msg)


def appeal_window_elapsed(msg="Appeal attempted more than 14 days after adjudication"):
    return ApiError("ERR_APPEAL_WINDOW_ELAPSED", 409, msg)


def facility_not_available(msg="Facility is MAINTENANCE_HOLD or RETIRED"):
    return ApiError("ERR_FACILITY_NOT_AVAILABLE", 409, msg)


def site_closed(msg="Site is CLOSED; no new requests, events, or facilities"):
    return ApiError("ERR_SITE_CLOSED", 409, msg)


def permit_not_cancellable(msg="Cancel attempted on permit not in ISSUED"):
    return ApiError("ERR_PERMIT_NOT_CANCELLABLE", 409, msg)


def empty_damage_claim(msg="DamageAssessment line_items empty or any repair_cost_cents <= 0"):
    return ApiError("ERR_EMPTY_DAMAGE_CLAIM", 422, msg)


def adjudication_exceeds(msg="adjudicated_amount_cents or final_amount_cents exceeds total_claimed_cents"):
    return ApiError("ERR_ADJUDICATION_EXCEEDS_CLAIM", 422, msg)


def renewal_not_renewable(msg="renewed_from_id references a series not owned by this renter or already renewed"):
    return ApiError("ERR_RENEWAL_NOT_RENEWABLE", 422, msg)
