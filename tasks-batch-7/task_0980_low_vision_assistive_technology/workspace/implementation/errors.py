"""Error classes and error ID constants per the scaffold error catalog."""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error ID constants (from scaffold §1.6)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
ERR_VALIDATION = "ERR_VALIDATION"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_PLAN_SUSPENDED = "ERR_PLAN_SUSPENDED"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_REFERRAL_NOT_ACCEPTED = "ERR_REFERRAL_NOT_ACCEPTED"
ERR_EVALUATION_NOT_FINAL = "ERR_EVALUATION_NOT_FINAL"
ERR_ORDER_NOT_ACTIVE = "ERR_ORDER_NOT_ACTIVE"
ERR_FUNDING_NOT_APPROVED = "ERR_FUNDING_NOT_APPROVED"
ERR_LOAN_STILL_ACTIVE = "ERR_LOAN_STILL_ACTIVE"
ERR_FUNDING_WINDOW_INVALID = "ERR_FUNDING_WINDOW_INVALID"
ERR_TRIAL_EXPIRED = "ERR_TRIAL_EXPIRED"
ERR_SESSION_OVERLAP = "ERR_SESSION_OVERLAP"
ERR_SUBSCRIPTION_OVERLAP = "ERR_SUBSCRIPTION_OVERLAP"
ERR_CATEGORY_MISMATCH = "ERR_CATEGORY_MISMATCH"
ERR_UNIT_NOT_AVAILABLE = "ERR_UNIT_NOT_AVAILABLE"
ERR_NO_ELIGIBLE_UNIT = "ERR_NO_ELIGIBLE_UNIT"
ERR_PLAN_SESSION_CAP = "ERR_PLAN_SESSION_CAP"
ERR_ASSESSMENT_INCOMPLETE = "ERR_ASSESSMENT_INCOMPLETE"
ERR_INSUFFICIENT_FUNDING = "ERR_INSUFFICIENT_FUNDING"


def unauthenticated(msg="Missing or unrecognized X-User-Role / X-User-ID headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden_role(msg="Acting role is not in the endpoint's role list"):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def validation(msg="Validation failed"):
    return ApiError(ERR_VALIDATION, 400, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def stale_version(msg="expected_client_version does not match Client.version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def invalid_state(msg="Entity not in a state from which the requested transition exists"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def plan_suspended(msg="Scheduling a session on a SUSPENDED or COMPLETED training plan"):
    return ApiError(ERR_PLAN_SUSPENDED, 409, msg)


def segregation(msg="Adjudicator must differ from the recorded submitter"):
    return ApiError(ERR_SEGREGATION_OF_DUTIES, 403, msg)


def referral_not_accepted(msg="Referral is not ACCEPTED"):
    return ApiError(ERR_REFERRAL_NOT_ACCEPTED, 409, msg)


def evaluation_not_final(msg="Evaluation is not FINALIZED"):
    return ApiError(ERR_EVALUATION_NOT_FINAL, 409, msg)


def order_not_active(msg="Order is not ACTIVE or CONVERTED"):
    return ApiError(ERR_ORDER_NOT_ACTIVE, 409, msg)


def funding_not_approved(msg="Funding authorization is not APPROVED"):
    return ApiError(ERR_FUNDING_NOT_APPROVED, 409, msg)


def loan_still_active(msg="Linked loan agreement is still ACTIVE or OVERDUE"):
    return ApiError(ERR_LOAN_STILL_ACTIVE, 409, msg)


def funding_window_invalid(msg="service_date outside [valid_from, valid_until]"):
    return ApiError(ERR_FUNDING_WINDOW_INVALID, 422, msg)


def trial_expired(msg="Trial conversion after trial_ends_at"):
    return ApiError(ERR_TRIAL_EXPIRED, 409, msg)


def session_overlap(msg="Session overlaps an existing session of the same instructor"):
    return ApiError(ERR_SESSION_OVERLAP, 409, msg)


def subscription_overlap(msg="Subscription overlaps an existing ACTIVE/PAST_DUE subscription for the same client and model"):
    return ApiError(ERR_SUBSCRIPTION_OVERLAP, 409, msg)


def category_mismatch(msg="Order's device model category differs from the evaluation's recommended_category"):
    return ApiError(ERR_CATEGORY_MISMATCH, 409, msg)


def unit_not_available(msg="Explicit device_unit_id is not IN_STOCK or belongs to a different model"):
    return ApiError(ERR_UNIT_NOT_AVAILABLE, 409, msg)


def no_eligible_unit(msg="Auto-selection pool is empty"):
    return ApiError(ERR_NO_ELIGIBLE_UNIT, 409, msg)


def plan_session_cap(msg="Non-cancelled session count has reached total_sessions"):
    return ApiError(ERR_PLAN_SESSION_CAP, 422, msg)


def assessment_incomplete(msg="Required scores still null at finalize"):
    return ApiError(ERR_ASSESSMENT_INCOMPLETE, 422, msg)


def insufficient_funding(msg="Claim provisional_total_cents exceeds remaining_amount_cents"):
    return ApiError(ERR_INSUFFICIENT_FUNDING, 422, msg)
