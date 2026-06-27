"""Error classes and error-ID constants.

Every error_id and http_status here is taken verbatim from PRD §5 (Error
Code Catalogue) and SCAFFOLD §1.6.
"""


class ApiError(Exception):
    """Carries an error_id + message + http_status to the error handler."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalog (PRD §5 / SCAFFOLD §1.6) ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                      # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_VALIDATION = "ERR_VALIDATION"                    # 422
ERR_REFERENCE_MISMATCH = "ERR_REFERENCE_MISMATCH"    # 422
ERR_INVALID_STATE = "ERR_INVALID_STATE"             # 409
ERR_EXAM_CLOSED = "ERR_EXAM_CLOSED"                 # 409
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"  # 403
ERR_LOCKDOWN_NOT_VERIFIED = "ERR_LOCKDOWN_NOT_VERIFIED"  # 409
ERR_OUTSIDE_TEST_WINDOW = "ERR_OUTSIDE_TEST_WINDOW"  # 422
ERR_PROCTOR_DOUBLE_BOOKED = "ERR_PROCTOR_DOUBLE_BOOKED"  # 409
ERR_CANDIDATE_OVERLAP = "ERR_CANDIDATE_OVERLAP"      # 409
ERR_PROCTOR_OVERLOADED = "ERR_PROCTOR_OVERLOADED"    # 409
ERR_SESSION_IN_PROGRESS = "ERR_SESSION_IN_PROGRESS"  # 409
ERR_NOT_VOIDED = "ERR_NOT_VOIDED"                    # 409
ERR_EMPTY_REPORT = "ERR_EMPTY_REPORT"               # 422
ERR_CHECKIN_TOO_EARLY = "ERR_CHECKIN_TOO_EARLY"     # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"             # 412


def unauthenticated(msg="Missing or unknown authentication headers."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Acting role is not permitted to perform this operation."):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="Referenced resource does not exist."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def validation(msg="Malformed body, missing required field, or invalid value."):
    return ApiError(ERR_VALIDATION, 422, msg)


def reference_mismatch(msg="Foreign-key targets are mutually inconsistent."):
    return ApiError(ERR_REFERENCE_MISMATCH, 422, msg)


def invalid_state(msg="Resource is not in a valid state for the requested transition."):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def exam_closed(msg="The exam is closed to new appointments."):
    return ApiError(ERR_EXAM_CLOSED, 409, msg)


def segregation(msg="Segregation of duties violated."):
    return ApiError(ERR_SEGREGATION_OF_DUTIES, 403, msg)


def lockdown_not_verified(msg="Identity verification has not passed for this lockdown-required exam."):
    return ApiError(ERR_LOCKDOWN_NOT_VERIFIED, 409, msg)


def outside_window(msg="Appointment effective window falls outside the exam test window."):
    return ApiError(ERR_OUTSIDE_TEST_WINDOW, 422, msg)


def proctor_double_booked(msg="Appointment overlaps another appointment of the same proctor."):
    return ApiError(ERR_PROCTOR_DOUBLE_BOOKED, 409, msg)


def candidate_overlap(msg="Candidate already has an overlapping appointment for the same exam."):
    return ApiError(ERR_CANDIDATE_OVERLAP, 409, msg)


def proctor_overloaded(msg="Proctor prospective load factor would exceed the ceiling."):
    return ApiError(ERR_PROCTOR_OVERLOADED, 409, msg)


def session_in_progress(msg="A non-terminal session still exists for this appointment."):
    return ApiError(ERR_SESSION_IN_PROGRESS, 409, msg)


def not_voided(msg="The session is not VOIDED."):
    return ApiError(ERR_NOT_VOIDED, 409, msg)


def empty_report(msg="Report session_ids empty or a referenced session is not terminal."):
    return ApiError(ERR_EMPTY_REPORT, 422, msg)


def checkin_too_early(msg="Operation attempted before the relevant clock instant."):
    return ApiError(ERR_CHECKIN_TOO_EARLY, 409, msg)


def stale_version(msg="Expected parent version does not match the parent's current version."):
    return ApiError(ERR_STALE_VERSION, 412, msg)
