"""Error classes carrying the scaffold's exact error_ids and HTTP statuses."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def unauthenticated(msg="Missing or unrecognized X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden(msg="Role not allowed on endpoint, or caller does not own the resource"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def validation(msg="Malformed request"):
    return ApiError("ERR_VALIDATION", 422, msg)


def not_found(msg="Resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def stale_version(msg="expected version does not match the entity's current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def invalid_window_state(msg="ConferenceWindow.status does not allow the requested operation"):
    return ApiError("ERR_INVALID_WINDOW_STATE", 409, msg)


def invalid_state(msg="Target entity is not in a valid state for the requested transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def family_restricted(msg="Family status RESTRICTED blocks family self-service booking and waitlist join"):
    return ApiError("ERR_FAMILY_RESTRICTED", 409, msg)


def teacher_inactive(msg="Teacher status INACTIVE blocks new bookings against that teacher's slots"):
    return ApiError("ERR_TEACHER_INACTIVE", 409, msg)


def slot_not_available(msg="Slot is not OPEN for the requested operation"):
    return ApiError("ERR_SLOT_NOT_AVAILABLE", 409, msg)


def no_active_offer(msg="WaitlistEntry is not OFFERED"):
    return ApiError("ERR_NO_ACTIVE_OFFER", 409, msg)


def booking_window_not_open(msg="open-booking attempted before booking_open_at"):
    return ApiError("ERR_BOOKING_WINDOW_NOT_OPEN", 422, msg)


def booking_window_not_closed(msg="lock attempted before booking_close_at"):
    return ApiError("ERR_BOOKING_WINDOW_NOT_CLOSED", 422, msg)


def cancellation_cutoff(msg="Family self-cancel/reschedule attempted after the cancellation cutoff"):
    return ApiError("ERR_CANCELLATION_CUTOFF", 422, msg)


def offer_expired(msg="Waitlist claim attempted after offer_expires_at"):
    return ApiError("ERR_OFFER_EXPIRED", 422, msg)


def invalid_day_window(msg="day_windows entry has end_at <= start_at or malformed date"):
    return ApiError("ERR_INVALID_DAY_WINDOW", 422, msg)


def family_schedule_conflict(msg="Candidate booking violates the family channel-dependent gap rule"):
    return ApiError("ERR_FAMILY_SCHEDULE_CONFLICT", 409, msg)


def interpreter_overlap(msg="Interpreter has an overlapping ASSIGNED/CONFIRMED assignment"):
    return ApiError("ERR_INTERPRETER_OVERLAP", 409, msg)


def interpreter_fatigue(msg="Assignment would create a zero-gap run longer than max_consecutive_minutes"):
    return ApiError("ERR_INTERPRETER_FATIGUE", 422, msg)


def interpreter_capacity(msg="Assignment would exceed interpreter_window_capacity"):
    return ApiError("ERR_INTERPRETER_CAPACITY_EXCEEDED", 422, msg)


def language_not_covered(msg="Interpreter's languages do not include the request language"):
    return ApiError("ERR_LANGUAGE_NOT_COVERED", 422, msg)


def no_eligible_interpreter(msg="Auto-assign found no eligible candidate"):
    return ApiError("ERR_NO_ELIGIBLE_INTERPRETER", 422, msg)


def duplicate_booking(msg="A CONFIRMED booking already exists for this student/teacher in this window"):
    return ApiError("ERR_DUPLICATE_BOOKING", 409, msg)


def duplicate_waitlist_entry(msg="A WAITING/OFFERED entry already exists, or a CONFIRMED booking exists for the pair"):
    return ApiError("ERR_DUPLICATE_WAITLIST_ENTRY", 409, msg)


def duplicate_teacher_link(msg="A StudentTeacherLink already exists for (student, teacher)"):
    return ApiError("ERR_DUPLICATE_TEACHER_LINK", 409, msg)


def channel_not_allowed(msg="Requested channel incompatible with slot/teacher/interpreter channel support"):
    return ApiError("ERR_CHANNEL_NOT_ALLOWED", 422, msg)


def already_has_interpreter_request(msg="Booking already has a non-terminal InterpreterRequest"):
    return ApiError("ERR_ALREADY_HAS_INTERPRETER_REQUEST", 409, msg)


def student_not_bookable(msg="Student enrollment_status is WITHDRAWN"):
    return ApiError("ERR_STUDENT_NOT_BOOKABLE", 422, msg)


def teacher_not_linked(msg="No StudentTeacherLink between student and the slot's teacher"):
    return ApiError("ERR_TEACHER_NOT_LINKED", 422, msg)


def teacher_day_full(msg="Teacher's CONFIRMED bookings on that day_label equal the effective daily cap"):
    return ApiError("ERR_TEACHER_DAY_FULL", 422, msg)


def family_limit_reached(msg="Family's CONFIRMED bookings in the window equal family_conf_cap"):
    return ApiError("ERR_FAMILY_LIMIT_REACHED", 422, msg)


def window_grid_locked(msg="Grid fields cannot change once slots exist"):
    return ApiError("ERR_WINDOW_GRID_LOCKED", 409, msg)


def slots_already_booked(msg="Slot regeneration refused because bookings reference the existing grid"):
    return ApiError("ERR_SLOTS_ALREADY_BOOKED", 409, msg)


def open_outreach_tasks(msg="Window archive blocked by OPEN or CONTACTED outreach tasks"):
    return ApiError("ERR_OPEN_OUTREACH_TASKS", 409, msg)
