"""Error catalog (SCAFFOLD §1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# -- Helpers raising exact catalog entries -----------------------------------

def err_unauthenticated(msg="Missing or unknown X-User-Role or X-User-ID"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden(msg="Role not authorized for this endpoint"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def err_not_owner(msg="Caller does not own the targeted resource"):
    return ApiError("ERR_NOT_OWNER", 403, msg)


def err_validation(msg="Missing required field, bad type, enum or range"):
    return ApiError("ERR_VALIDATION", 400, msg)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid_state(msg="State-machine precondition failed"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_registration_not_open(msg="Contest or category not open for registration"):
    return ApiError("ERR_REGISTRATION_NOT_OPEN", 409, msg)


def err_prop_banned(msg="prop_declarations include a banned prop type"):
    return ApiError("ERR_PROP_BANNED", 422, msg)


def err_safety_not_approved(msg="Entry safety_status is not APPROVED"):
    return ApiError("ERR_SAFETY_NOT_APPROVED", 409, msg)


def err_consent_required(msg="LIVESTREAM consent not GRANTED"):
    return ApiError("ERR_CONSENT_REQUIRED", 409, msg)


def err_judge_conflict(msg="Judge's linked contestant has an entry in this category"):
    return ApiError("ERR_JUDGE_CONFLICT", 409, msg)


def err_duplicate_scoresheet(msg="Scoresheet already exists for (judge, entry, phase)"):
    return ApiError("ERR_DUPLICATE_SCORESHEET", 409, msg)


def err_duplicate_entry(msg="Duplicate entry or per-contestant entry cap reached"):
    return ApiError("ERR_DUPLICATE_ENTRY", 409, msg)


def err_entry_category_mismatch(msg="Entry category differs from slot category"):
    return ApiError("ERR_ENTRY_CATEGORY_MISMATCH", 409, msg)


def err_category_full(msg="Category entry quota reached"):
    return ApiError("ERR_CATEGORY_FULL", 409, msg)


def err_division_age(msg="Contestant does not meet JUNIOR age eligibility"):
    return ApiError("ERR_DIVISION_AGE_INELIGIBLE", 422, msg)


def err_slot_overlap(msg="Pre-judging slot overlaps an existing slot on this panel"):
    return ApiError("ERR_SLOT_OVERLAP", 409, msg)


def err_sequence_conflict(msg="sequence_number conflict among active stage slots"):
    return ApiError("ERR_SEQUENCE_CONFLICT", 409, msg)


def err_slot_outside_window(msg="Slot outside contest window"):
    return ApiError("ERR_SLOT_OUTSIDE_WINDOW", 422, msg)


def err_booking_in_past(msg="Booking start_at precedes logical now"):
    return ApiError("ERR_BOOKING_IN_PAST", 422, msg)


def err_green_room_inaccessible(msg="Room is not accessibility-equipped"):
    return ApiError("ERR_GREEN_ROOM_INACCESSIBLE", 422, msg)


def err_green_room_full(msg="Green-room capacity reached"):
    return ApiError("ERR_GREEN_ROOM_FULL", 409, msg)


def err_prize_budget_exceeded(msg="Award exceeds contest prize budget"):
    return ApiError("ERR_PRIZE_BUDGET_EXCEEDED", 422, msg)


def err_tax_form_required(msg="W-9 required before tax reporting"):
    return ApiError("ERR_TAX_FORM_REQUIRED", 409, msg)


def err_segregation_of_duties(msg="Creator may not approve own award"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


def err_scoresheets_not_locked(msg="Draft or submitted scoresheets remain in the category"):
    return ApiError("ERR_SCORESHEETS_NOT_LOCKED", 409, msg)


def err_category_not_tabulated(msg="Category is not TABULATED"):
    return ApiError("ERR_CATEGORY_NOT_TABULATED", 409, msg)


def err_placement_not_found(msg="No PLACED entry at requested rank"):
    return ApiError("ERR_PLACEMENT_NOT_FOUND", 409, msg)


def err_no_eligible_entries(msg="No PERFORMED entries in category"):
    return ApiError("ERR_NO_ELIGIBLE_ENTRIES", 409, msg)


def err_stale_version(msg="Stale version (optimistic concurrency)"):
    return ApiError("ERR_STALE_VERSION", 412, msg)
