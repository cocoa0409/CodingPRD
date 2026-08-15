"""Error classes and error ID constants (error catalog from PRD §5 / SCAFFOLD §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_unauthenticated(msg="X-User-Role header missing or not a recognized role"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_forbidden(msg="Role not permitted on this endpoint"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def err_invalid_request(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_stale_case_version(msg="expected_case_version does not match the case's current version"):
    return ApiError("ERR_STALE_CASE_VERSION", msg, 412)


def err_invalid_state(msg="Resource is not in a valid state for the requested transition"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_case_not_active(msg="Owning case is not in a required status for this operation"):
    return ApiError("ERR_CASE_NOT_ACTIVE", msg, 409)


def err_engagement_not_approved(msg="Engagement is not in APPROVED status"):
    return ApiError("ERR_ENGAGEMENT_NOT_APPROVED", msg, 409)


def err_plan_not_executing(msg="The payment's plan is not in APPROVED status"):
    return ApiError("ERR_PLAN_NOT_EXECUTING", msg, 409)


def err_authorization_required(msg="Asset value exceeds the authority limit; an authorization_id is required"):
    return ApiError("ERR_AUTHORIZATION_REQUIRED", msg, 409)


def err_authorization_mismatch(msg="Supplied authorization is not APPROVED, has the wrong request_type, or references a different asset"):
    return ApiError("ERR_AUTHORIZATION_MISMATCH", msg, 409)


def err_claim_barred(msg="Claim filed after the case bar_date"):
    return ApiError("ERR_CLAIM_BARRED", msg, 422)


def err_status_report_overdue(msg="A periodic status report is overdue for this case"):
    return ApiError("ERR_STATUS_REPORT_OVERDUE", msg, 422)


def err_report_period_overlap(msg="Report period overlaps another non-REJECTED report of the same case"):
    return ApiError("ERR_REPORT_PERIOD_OVERLAP", msg, 409)


def err_report_period_gap(msg="Report period_start does not equal the case's next_report_period_start"):
    return ApiError("ERR_REPORT_PERIOD_GAP", msg, 409)


def err_fee_period_overlap(msg="Fee application period overlaps another non-DENIED application of the same engagement"):
    return ApiError("ERR_FEE_PERIOD_OVERLAP", msg, 409)


def err_plan_already_open(msg="Another plan of the case is FILED or APPROVED"):
    return ApiError("ERR_PLAN_ALREADY_OPEN", msg, 409)


def err_engagement_already_active(msg="Another engagement of the case with the same role_type is PROPOSED or APPROVED"):
    return ApiError("ERR_ENGAGEMENT_ALREADY_ACTIVE", msg, 409)


def err_undetermined_claims(msg="A claim of the case remains in FILED status"):
    return ApiError("ERR_UNDETERMINED_CLAIMS", msg, 409)


def err_discharge_blocked(msg="Discharge aggregate preconditions are not met"):
    return ApiError("ERR_DISCHARGE_BLOCKED", msg, 409)


def err_duplicate_case_number(msg="case_number already exists within the same court_jurisdiction"):
    return ApiError("ERR_DUPLICATE_CASE_NUMBER", msg, 409)


def err_collateral_not_eligible(msg="Collateral asset is ABANDONED"):
    return ApiError("ERR_COLLATERAL_NOT_ELIGIBLE", msg, 409)


def err_senior_class_unpaid(msg="A payment of a strictly senior priority class on the same plan is still SCHEDULED"):
    return ApiError("ERR_SENIOR_CLASS_UNPAID", msg, 409)


def err_insufficient_estate_funds(msg="cash_on_hand_cents is below the amount the operation would debit"):
    return ApiError("ERR_INSUFFICIENT_ESTATE_FUNDS", msg, 409)


def err_reserve_exceeds_pool(msg="reserve_cents exceeds cash_on_hand_cents at plan filing"):
    return ApiError("ERR_RESERVE_EXCEEDS_POOL", msg, 422)


def err_fee_cap_exceeded(msg="Approving would push the engagement's committed fees beyond fee_cap_cents"):
    return ApiError("ERR_FEE_CAP_EXCEEDED", msg, 422)


def err_amount_exceeds_request(msg="approved_amount_cents exceeds requested_amount_cents"):
    return ApiError("ERR_AMOUNT_EXCEEDS_REQUEST", msg, 422)


def err_allowed_exceeds_filed(msg="allowed_amount_cents exceeds filed_amount_cents"):
    return ApiError("ERR_ALLOWED_EXCEEDS_FILED", msg, 422)
