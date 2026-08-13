"""Error catalog for the Public Pension Administration API.

Every error carries the exact error_id and HTTP status from the PRD §5
catalogue. ApiError is raised anywhere in the request lifecycle and rendered
by the central error handler in app.py.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(msg="Missing or unknown X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden(msg="Role not permitted for this endpoint or ownership check failed"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def err_segregation(msg="Segregation of duties violated"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid_request(msg="Malformed request body"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_stale_version(msg="Expected version does not match current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def err_invalid_state(msg="Resource is in an invalid state for this transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_member_not_active(msg="Member is not ACTIVE"):
    return ApiError("ERR_MEMBER_NOT_ACTIVE", 409, msg)


def err_member_deceased(msg="Operation blocked: member is DECEASED"):
    return ApiError("ERR_MEMBER_DECEASED", 409, msg)


def err_active_application_exists(msg="Member already has a non-terminal application of this type"):
    return ApiError("ERR_ACTIVE_APPLICATION_EXISTS", 409, msg)


def err_quote_expired(msg="Quote has expired"):
    return ApiError("ERR_QUOTE_EXPIRED", 422, msg)


def err_plan_not_active(msg="Purchase is not in PLAN_ACTIVE"):
    return ApiError("ERR_PLAN_NOT_ACTIVE", 409, msg)


def err_benefit_not_active(msg="Benefit is TERMINATED"):
    return ApiError("ERR_BENEFIT_NOT_ACTIVE", 409, msg)


def err_benefit_not_terminated(msg="Member's benefit is not TERMINATED"):
    return ApiError("ERR_BENEFIT_NOT_TERMINATED", 409, msg)


def err_not_vested(msg="Member has fewer than 5.0 years of service"):
    return ApiError("ERR_NOT_VESTED", 422, msg)


def err_under_retirement_age(msg="Member is under 60 completed years of age"):
    return ApiError("ERR_MEMBER_UNDER_RETIREMENT_AGE", 422, msg)


def err_outstanding_balance(msg="Member has a service purchase in PLAN_ACTIVE"):
    return ApiError("ERR_OUTSTANDING_BALANCE", 422, msg)


def err_lines_pending(msg="Contribution report still has PENDING lines"):
    return ApiError("ERR_LINES_PENDING", 422, msg)


def err_reconciliation_variance(msg="Accepted total does not equal declared total"):
    return ApiError("ERR_RECONCILIATION_VARIANCE", 422, msg)


def err_duplicate_line_period(msg="A line for this member and fiscal year already exists in the report"):
    return ApiError("ERR_DUPLICATE_LINE_PERIOD", 409, msg)


def err_report_period_overlap(msg="Report period overlaps another report of this employer"):
    return ApiError("ERR_REPORT_PERIOD_OVERLAP", 409, msg)


def err_purchase_period_overlap(msg="Purchase service period shares a day with an already-credited fiscal year"):
    return ApiError("ERR_PURCHASE_PERIOD_OVERLAP", 409, msg)


def err_designation_revoked(msg="Beneficiary designation has been revoked"):
    return ApiError("ERR_DESIGNATION_REVOKED", 422, msg)


def err_no_survivor_entitlement(msg="Originating option election does not entitle survivors"):
    return ApiError("ERR_NO_SURVIVOR_ENTITLEMENT", 422, msg)


def err_claim_deadline_passed(msg="Claim filed more than 365 days after member death"):
    return ApiError("ERR_CLAIM_DEADLINE_PASSED", 422, msg)


def err_appeal_window_closed(msg="Appeal filed more than 60 days after the decision"):
    return ApiError("ERR_APPEAL_WINDOW_CLOSED", 422, msg)
