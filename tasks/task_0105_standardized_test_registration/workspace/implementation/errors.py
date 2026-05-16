"""Custom exception class and the error catalog from SCAFFOLD.yaml §1.6."""


class APIError(Exception):
    """Carries error_id, message, and http_status for the response envelope."""

    def __init__(self, error_id: str, http_status: int, message: str = ""):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


# Pre-defined error constructors for clarity.
def err(error_id: str, http_status: int, message: str = "") -> APIError:
    return APIError(error_id, http_status, message)


# Auth
def err_missing_or_invalid_user_context_header(msg: str = "X-User-ID or X-User-Role missing or malformed"):
    return APIError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400, msg)


def err_insufficient_permissions(msg: str = "Role lacks permission for the endpoint"):
    return APIError("ERR_INSUFFICIENT_PERMISSIONS", 403, msg)


# Existence
def err_test_event_not_found():
    return APIError("ERR_TEST_EVENT_NOT_FOUND", 404, "TestEvent not found")


def err_test_center_not_found():
    return APIError("ERR_TEST_CENTER_NOT_FOUND", 404, "TestCenter not found")


def err_test_center_capacity_not_found():
    return APIError("ERR_TEST_CENTER_CAPACITY_NOT_FOUND", 404, "TestCenterCapacity not found")


def err_candidate_not_found():
    return APIError("ERR_CANDIDATE_NOT_FOUND", 404, "Candidate not found")


def err_registration_not_found():
    return APIError("ERR_REGISTRATION_NOT_FOUND", 404, "Registration not found")


def err_accommodation_request_not_found():
    return APIError("ERR_ACCOMMODATION_REQUEST_NOT_FOUND", 404, "AccommodationRequest not found")


def err_id_verification_not_found():
    return APIError("ERR_ID_VERIFICATION_NOT_FOUND", 404, "IDVerification not found")


def err_score_report_not_found():
    return APIError("ERR_SCORE_REPORT_NOT_FOUND", 404, "ScoreReport not found")


# State
def err_registration_closed():
    return APIError("ERR_REGISTRATION_CLOSED", 409, "TestEvent registration is closed")


def err_invalid_registration_state(msg: str = "Registration not in legal state for this operation"):
    return APIError("ERR_INVALID_REGISTRATION_STATE", 409, msg)


def err_invalid_accommodation_state(msg: str = "AccommodationRequest not in legal state for this transition"):
    return APIError("ERR_INVALID_ACCOMMODATION_STATE", 409, msg)


def err_invalid_id_verification_state(msg: str = "IDVerification not in legal state for this operation"):
    return APIError("ERR_INVALID_ID_VERIFICATION_STATE", 409, msg)


def err_deadline_extension_exhausted():
    return APIError("ERR_DEADLINE_EXTENSION_EXHAUSTED", 409, "Deadline has already been extended")


# SOD / concurrency
def err_not_pinned_reviewer():
    return APIError("ERR_NOT_PINNED_REVIEWER", 403, "Caller is not the pinned reviewer")


def err_clep_award_already_posted():
    return APIError("ERR_CLEP_AWARD_ALREADY_POSTED", 409, "CLEPCreditAward already posted for this ScoreReport")


# Business referential
def err_id_not_cleared():
    return APIError("ERR_ID_NOT_CLEARED", 409, "IDVerification has not been cleared")


def err_accommodation_pending():
    return APIError("ERR_ACCOMMODATION_PENDING", 409, "AccommodationRequest is still pending")


# Business safety
def err_cross_state_id_mismatch():
    return APIError("ERR_CROSS_STATE_ID_MISMATCH", 422, "ID issuing state does not match Candidate home state")


def err_id_expired_before_test():
    return APIError("ERR_ID_EXPIRED_BEFORE_TEST", 422, "ID document expires on or before test date")


# Business temporal
def err_check_in_window_closed():
    return APIError("ERR_CHECK_IN_WINDOW_CLOSED", 409, "Check-in window is closed")


def err_accommodation_deadline_passed():
    return APIError("ERR_ACCOMMODATION_DEADLINE_PASSED", 422, "AccommodationRequest submission deadline has passed")


def err_test_center_time_conflict():
    return APIError("ERR_TEST_CENTER_TIME_CONFLICT", 409, "TestCenter already hosts an overlapping TestEvent")


def err_candidate_session_overlap():
    return APIError("ERR_CANDIDATE_SESSION_OVERLAP", 409, "Candidate already has an overlapping registration")


# Business constraint
def err_duplicate_registration():
    return APIError("ERR_DUPLICATE_REGISTRATION", 409, "Duplicate registration for this candidate and event")


def err_accommodation_not_eligible():
    return APIError("ERR_ACCOMMODATION_NOT_ELIGIBLE", 422, "Candidate is not eligible for accommodations")


def err_duplicate_accommodation():
    return APIError("ERR_DUPLICATE_ACCOMMODATION", 409, "Duplicate accommodation request for this candidate and event")


# Business fiscal
def err_capacity_exhausted():
    return APIError("ERR_CAPACITY_EXHAUSTED", 409, "Capacity exhausted at requested test center")


# CLEP
def err_clep_invalid_context():
    return APIError("ERR_CLEP_INVALID_CONTEXT", 422, "CLEPCreditAward requires CLEP TestEvent")


def err_clep_subject_unrecognized():
    return APIError("ERR_CLEP_SUBJECT_UNRECOGNIZED", 422, "TestEvent subject is not recognized for CLEP")


# Misc
def err_invalid_request(msg: str = "Invalid request body or parameters"):
    return APIError("ERR_INVALID_REQUEST", 400, msg)


def err_version_conflict():
    return APIError("ERR_VERSION_CONFLICT", 409, "Version conflict — resource has been modified")
