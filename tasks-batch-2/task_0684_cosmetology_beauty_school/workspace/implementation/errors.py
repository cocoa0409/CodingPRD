"""Error catalogue (PRD Section 5 / scaffold §1.6).

All error_id values are generic per this PRD (ERR_NOT_FOUND, ERR_FK_NOT_FOUND,
etc.) — they are NOT resource-specific.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def _e(error_id, http_status, message=None):
    return ApiError(error_id, http_status, message)


# --- auth (priority 1-2) ---
def unauthenticated(msg="Missing or malformed auth context"):
    return _e("ERR_UNAUTHENTICATED", 401, msg)


def forbidden_role(msg="Role not permitted for this operation"):
    return _e("ERR_FORBIDDEN_ROLE", 403, msg)


def not_resource_owner(msg="Acting user does not own this resource"):
    return _e("ERR_NOT_RESOURCE_OWNER", 403, msg)


# --- existence (priority 3-4) ---
def not_found(msg="Resource not found"):
    return _e("ERR_NOT_FOUND", 404, msg)


def fk_not_found(msg="Referenced entity does not exist"):
    return _e("ERR_FK_NOT_FOUND", 404, msg)


# --- request shape (priority 5) ---
def invalid_request(msg="Invalid request"):
    return _e("ERR_INVALID_REQUEST", 422, msg)


def hours_exceed_scheduled(msg="hours may not exceed scheduled_hours"):
    return _e("ERR_HOURS_EXCEED_SCHEDULED", 422, msg)


# --- domain constraints ---
def duplicate_key(msg="Unique constraint violated"):
    return _e("ERR_DUPLICATE_KEY", 409, msg)


def invalid_period(msg="payment_period invalid or already used"):
    return _e("ERR_INVALID_PERIOD", 409, msg)


def invalid_state(msg="Requested transition not defined from current state"):
    return _e("ERR_INVALID_STATE", 409, msg)


def instructor_license_invalid(msg="Instructor inactive or license expired"):
    return _e("ERR_INSTRUCTOR_LICENSE_INVALID", 409, msg)


def clinic_phase_not_reached(msg="Enrollment has not reached the clinic phase"):
    return _e("ERR_CLINIC_PHASE_NOT_REACHED", 409, msg)


def station_double_booked(msg="Station reservation window overlaps an existing reservation"):
    return _e("ERR_STATION_DOUBLE_BOOKED", 409, msg)


def clinic_slot_conflict(msg="Clinic slot collides within the 15-minute turnover buffer"):
    return _e("ERR_CLINIC_SLOT_CONFLICT", 409, msg)


def station_unavailable(msg="Station out of service or station_type mismatched"):
    return _e("ERR_STATION_UNAVAILABLE", 409, msg)


def period_hours_not_earned(msg="actual_hours below period_hours"):
    return _e("ERR_PERIOD_HOURS_NOT_EARNED", 409, msg)


def period_weeks_not_elapsed(msg="period_weeks have not elapsed"):
    return _e("ERR_PERIOD_WEEKS_NOT_ELAPSED", 409, msg)


def exam_not_ready(msg="Exam readiness/competency/hours gate unmet"):
    return _e("ERR_EXAM_NOT_READY", 409, msg)


def outstanding_balance(msg="Outstanding ledger balance blocks graduation"):
    return _e("ERR_OUTSTANDING_BALANCE", 409, msg)


# --- OCC (priority 18) ---
def stale_enrollment_version(msg="expected_enrollment_version does not match live version"):
    return _e("ERR_STALE_ENROLLMENT_VERSION", 412, msg)
