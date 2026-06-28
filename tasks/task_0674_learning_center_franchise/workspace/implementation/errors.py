"""Error catalog (SCAFFOLD §1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# auth / existence / request
def unauthenticated(msg="Missing or unknown authentication headers."):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden(msg="Acting role is not permitted for this operation."):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def not_found(msg="Referenced resource does not exist."):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_request(msg="Request body is malformed."):
    return ApiError("ERR_INVALID_REQUEST", 422, msg)


def score_out_of_range(msg="Worksheet grade score must be in 0..100."):
    return ApiError("ERR_SCORE_OUT_OF_RANGE", 422, msg)


# concurrency / state
def stale_version(msg="Expected version does not match current version."):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def invalid_state(msg="Resource is not in a valid state for this transition."):
    return ApiError("ERR_INVALID_STATE", 409, msg)


# center / agreement
def agreement_not_active(msg="Center activation requires an ACTIVE franchise agreement."):
    return ApiError("ERR_AGREEMENT_NOT_ACTIVE", 409, msg)


def center_operating(msg="Cannot terminate the agreement of an OPERATING center."):
    return ApiError("ERR_CENTER_OPERATING", 409, msg)


def center_not_operating(msg="Operation requires the center to be OPERATING."):
    return ApiError("ERR_CENTER_NOT_OPERATING", 409, msg)


def royalty_rate_invalid(msg="royalty_rate_bps + marketing_fee_bps exceeds 10000."):
    return ApiError("ERR_ROYALTY_RATE_INVALID", 409, msg)


def territory_conflict(msg="Another center already uses this territory_code."):
    return ApiError("ERR_TERRITORY_CONFLICT", 409, msg)


# enrollment / curriculum
def diagnostic_missing(msg="Placement attempted without a diagnostic_raw_score."):
    return ApiError("ERR_DIAGNOSTIC_MISSING", 409, msg)


def level_subject_mismatch(msg="Level does not belong to the enrollment's subject."):
    return ApiError("ERR_LEVEL_SUBJECT_MISMATCH", 409, msg)


def prereq_cycle(msg="prereq_level_id would create a cycle or references a non-lower-rank level."):
    return ApiError("ERR_PREREQ_CYCLE", 409, msg)


def enrollment_not_active(msg="Operation requires the parent enrollment to be ACTIVE."):
    return ApiError("ERR_ENROLLMENT_NOT_ACTIVE", 409, msg)


# session / attendance
def ratio_exceeded(msg="Booking would exceed seat_cap, or seat_cap exceeds instructor_ratio_cap."):
    return ApiError("ERR_RATIO_EXCEEDED", 409, msg)


def session_overlap(msg="Enrollment already has a seat on an overlapping session at this center."):
    return ApiError("ERR_SESSION_OVERLAP", 409, msg)


def instructor_double_booked(msg="Instructor already staffs a session whose buffered interval overlaps."):
    return ApiError("ERR_INSTRUCTOR_DOUBLE_BOOKED", 409, msg)


def session_not_open(msg="Check-in requires the session to be OPEN."):
    return ApiError("ERR_SESSION_NOT_OPEN", 409, msg)


def session_not_started(msg="Cannot close a session before its start_at."):
    return ApiError("ERR_SESSION_NOT_STARTED", 409, msg)


# invoice
def empty_invoice(msg="Cannot issue an invoice with zero billable components."):
    return ApiError("ERR_EMPTY_INVOICE", 409, msg)


def payment_amount_mismatch(msg="Payment amount_cents must equal Invoice.total_due_cents."):
    return ApiError("ERR_PAYMENT_AMOUNT_MISMATCH", 409, msg)
