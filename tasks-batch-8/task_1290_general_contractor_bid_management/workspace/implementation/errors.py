"""Error catalog — every error_id and HTTP status from the scaffold."""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- 400 ---
def err_missing_context(msg="X-User-ID or X-User-Role header missing, or role not declared"):
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400, msg)


def err_invalid_request(msg="Invalid request payload"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


# --- 403 ---
def err_forbidden_role(msg="Caller role not authorized for this endpoint"):
    return ApiError("ERR_FORBIDDEN_ROLE", 403, msg)


def err_forbidden_ownership(msg="Subcontractor may only act on its own resources"):
    return ApiError("ERR_FORBIDDEN_OWNERSHIP", 403, msg)


def err_sod(msg="Award decision caller must differ from recommendation drafter"):
    return ApiError("ERR_SOD_VIOLATION", 403, msg)


# --- 404 ---
def err_package_not_found(msg="Bid package not found"):
    return ApiError("ERR_BID_PACKAGE_NOT_FOUND", 404, msg)


def err_subcontractor_not_found(msg="Subcontractor not found"):
    return ApiError("ERR_SUBCONTRACTOR_NOT_FOUND", 404, msg)


def err_prequal_not_found(msg="Prequal application not found"):
    return ApiError("ERR_PREQUAL_APPLICATION_NOT_FOUND", 404, msg)


def err_invitation_not_found(msg="Invitation not found"):
    return ApiError("ERR_INVITATION_NOT_FOUND", 404, msg)


def err_addendum_not_found(msg="Addendum not found"):
    return ApiError("ERR_ADDENDUM_NOT_FOUND", 404, msg)


def err_bid_not_found(msg="Bid not found"):
    return ApiError("ERR_BID_NOT_FOUND", 404, msg)


def err_resource_not_found(msg="Resource not found"):
    return ApiError("ERR_RESOURCE_NOT_FOUND", 404, msg)


def err_ack_not_found(msg="No PENDING acknowledgment exists for this addendum/subcontractor"):
    return ApiError("ERR_ACKNOWLEDGMENT_NOT_FOUND", 404, msg)


# --- 409 ---
def err_package_invalid_state(msg="Bid package not in a permitted state for this trigger"):
    return ApiError("ERR_PACKAGE_INVALID_STATE", 409, msg)


def err_package_not_accepting_bids(msg="Package is not PUBLISHED"):
    return ApiError("ERR_PACKAGE_NOT_ACCEPTING_BIDS", 409, msg)


def err_invitation_invalid_state(msg="Invitation status does not permit this transition"):
    return ApiError("ERR_INVITATION_INVALID_STATE", 409, msg)


def err_application_invalid_state(msg="Application not in a permitted state for this trigger"):
    return ApiError("ERR_APPLICATION_INVALID_STATE", 409, msg)


def err_bid_invalid_state(msg="Bid not in a permitted state for this trigger"):
    return ApiError("ERR_BID_INVALID_STATE", 409, msg)


def err_invalid_resource_state(msg="Resource not in a permitted state for this trigger"):
    return ApiError("ERR_INVALID_RESOURCE_STATE", 409, msg)


def err_leveling_locked(msg="Leveling writes are locked in the current package state"):
    return ApiError("ERR_LEVELING_LOCKED", 409, msg)


def err_prequal_window_overlap(msg="Another live prequalification application exists"):
    return ApiError("ERR_PREQUAL_WINDOW_OVERLAP", 409, msg)


def err_invitation_declined(msg="Invitation is DECLINED"):
    return ApiError("ERR_INVITATION_DECLINED", 409, msg)


def err_duplicate_bid(msg="A SUBMITTED bid already exists for this package and subcontractor"):
    return ApiError("ERR_DUPLICATE_BID", 409, msg)


def err_duplicate_invitation(msg="An invitation already exists for this package and subcontractor"):
    return ApiError("ERR_DUPLICATE_INVITATION", 409, msg)


def err_duplicate_license(msg="license_number already registered"):
    return ApiError("ERR_DUPLICATE_LICENSE_NUMBER", 409, msg)


def err_active_recommendation(msg="An active recommendation already exists for this package"):
    return ApiError("ERR_ACTIVE_RECOMMENDATION_EXISTS", 409, msg)


def err_room_overlap(msg="Interview room overlap with a SCHEDULED interview"):
    return ApiError("ERR_INTERVIEW_ROOM_OVERLAP", 409, msg)


# --- 422 ---
def err_no_invited_bidders(msg="Publish requires at least one invitation"):
    return ApiError("ERR_NO_INVITED_BIDDERS", 422, msg)


def err_deadline_passed(msg="Logical now must be strictly before bid_due_at"):
    return ApiError("ERR_BID_DEADLINE_PASSED", 422, msg)


def err_deadline_not_reached(msg="Logical now must be at or after bid_due_at"):
    return ApiError("ERR_BID_DEADLINE_NOT_REACHED", 422, msg)


def err_prequal_not_approved(msg="Caller has no currently-approved prequalification"):
    return ApiError("ERR_PREQUAL_NOT_APPROVED", 422, msg)


def err_score_below_threshold(msg="verified_score below the 70 pass threshold"):
    return ApiError("ERR_PREQUAL_SCORE_BELOW_THRESHOLD", 422, msg)


def err_invitation_not_bidding(msg="Caller's invitation is not in BIDDING status"):
    return ApiError("ERR_INVITATION_NOT_BIDDING", 422, msg)


def err_no_compliant_bids(msg="Tabulation would leave zero compliant bids"):
    return ApiError("ERR_NO_COMPLIANT_BIDS", 422, msg)


def err_recommended_bid_ineligible(msg="recommended_bid_id is not a SUBMITTED bid of this package"):
    return ApiError("ERR_RECOMMENDED_BID_INELIGIBLE", 422, msg)


def err_invalid_time_range(msg="scheduled_start must be strictly before scheduled_end"):
    return ApiError("ERR_INVALID_TIME_RANGE", 422, msg)


# --- 402 ---
def err_bond_insufficient(msg="bond_amount_cents below the required bid bond"):
    return ApiError("ERR_BID_BOND_INSUFFICIENT", 402, msg)


# --- 412 ---
def err_stale_version(msg="expected_bid_version does not match the bid's current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def err_stale_package_version(msg="expected_bid_package_version does not match the package's current version"):
    return ApiError("ERR_STALE_PACKAGE_VERSION", 412, msg)
