"""Error classes carrying scaffold-declared error_id + http_status."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_unauthenticated(msg="Missing or invalid X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_unauthorized(msg="Role not permitted to invoke the endpoint"):
    return ApiError("ERR_UNAUTHORIZED", msg, 403)


def err_not_found(msg="Path-referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_invalid_request(msg="Required input field missing or malformed"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_invalid_state(msg="Target resource not in a state from which the requested transition exists"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_stale_version(msg="expected_*_version does not match the parent entity's current version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def err_not_owner(msg="Entity-backed actor id does not match the resource owner FK"):
    return ApiError("ERR_NOT_OWNER", msg, 403)


def err_segregation(msg="Same person attempted two segregated steps"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", msg, 422)


def err_ladder_rung(msg="Application target level is not exactly one rung above nurse's current level"):
    return ApiError("ERR_LADDER_RUNG_VIOLATION", msg, 422)


def err_no_active_criterion(msg="No active LadderCriterion covers the target level at the current clock position"):
    return ApiError("ERR_NO_ACTIVE_CRITERION", msg, 422)


def err_criterion_window_overlap(msg="Criterion validity window overlaps an existing criterion for the same target level"):
    return ApiError("ERR_CRITERION_WINDOW_OVERLAP", msg, 409)


def err_differential_monotonicity(msg="Differential amounts across active criteria violate CN_IV > CN_III > CN_II"):
    return ApiError("ERR_DIFFERENTIAL_MONOTONICITY", msg, 422)


def err_quorum_exceeded(msg="Assignment would exceed quorum of non-terminal reviewers on the application"):
    return ApiError("ERR_QUORUM_EXCEEDED", msg, 422)


def err_duplicate_reviewer(msg="Reviewer already holds a PENDING or SCORED assignment on this application"):
    return ApiError("ERR_DUPLICATE_REVIEWER", msg, 409)


def err_review_window_expired(msg="Score submitted after the 14-day review window"):
    return ApiError("ERR_REVIEW_WINDOW_EXPIRED", msg, 422)


def err_participation_points_range(msg="Points outside [1,40] or COMMITTEE_SEAT above 20"):
    return ApiError("ERR_PARTICIPATION_POINTS_RANGE", msg, 422)


def err_certification_date_order(msg="expires_on not strictly greater than obtained_on"):
    return ApiError("ERR_CERTIFICATION_DATE_ORDER", msg, 422)


def err_renewal_mismatch(msg="renewal_of_id resolves to a different nurse or different track"):
    return ApiError("ERR_RENEWAL_MISMATCH", msg, 422)


def err_certification_overlap(msg="Nurse would hold two CURRENT same-track certifications with overlapping intervals"):
    return ApiError("ERR_CERTIFICATION_OVERLAP", msg, 409)


def err_claim_exceeds_fee(msg="Claimed amount exceeds exam fee remaining on the certification"):
    return ApiError("ERR_CLAIM_EXCEEDS_FEE", msg, 422)


def err_reimbursement_cap_exhausted(msg="Per-nurse fiscal-year reimbursement ceiling reached"):
    return ApiError("ERR_REIMBURSEMENT_CAP_EXHAUSTED", msg, 402)


def err_budget_exceeded(msg="Unit budget guard fails at payment time"):
    return ApiError("ERR_BUDGET_EXCEEDED", msg, 402)


def err_cannot_demote_floor(msg="Demotion requested for a CN_I nurse"):
    return ApiError("ERR_CANNOT_DEMOTE_FLOOR", msg, 422)


def err_maintenance_score_insufficient(msg="SUSTAIN requested but maintenance score below threshold"):
    return ApiError("ERR_MAINTENANCE_SCORE_INSUFFICIENT", msg, 422)


def err_review_cycle_exhausted(msg="Return-for-revision requested when review_cycle already 3"):
    return ApiError("ERR_REVIEW_CYCLE_EXHAUSTED", msg, 422)


def err_stale_reference(msg="Pinned criterion modified since submission, or certification no longer CURRENT at decision time"):
    return ApiError("ERR_STALE_REFERENCE", msg, 409)
