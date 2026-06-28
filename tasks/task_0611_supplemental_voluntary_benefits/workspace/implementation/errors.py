"""Error classes and error-id constants (scaffold §1.6 / PRD §5).

Every error carries error_id, message, and http_status. The error_id values and
HTTP statuses are taken verbatim from the PRD error catalogue.
"""

# --- auth / existence ---
ERR_MISSING_USER_CONTEXT = "ERR_MISSING_USER_CONTEXT"   # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"               # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                         # 404

# --- referential / state ---
ERR_REFERENCE_MISMATCH = "ERR_REFERENCE_MISMATCH"       # 409
ERR_INVALID_STATE = "ERR_INVALID_STATE"                 # 409
ERR_PRODUCT_NOT_OPEN = "ERR_PRODUCT_NOT_OPEN"           # 409
ERR_SCHEDULE_EMPTY = "ERR_SCHEDULE_EMPTY"               # 409
ERR_EMPLOYEE_TERMINATED = "ERR_EMPLOYEE_TERMINATED"     # 409
ERR_SECTION125_INACTIVE = "ERR_SECTION125_INACTIVE"     # 409

# --- claim business ---
ERR_EVENT_BEFORE_COVERAGE = "ERR_EVENT_BEFORE_COVERAGE"  # 422
ERR_EVENT_NOT_COVERED = "ERR_EVENT_NOT_COVERED"          # 422
ERR_ACCOUNT_NOT_VERIFIED = "ERR_ACCOUNT_NOT_VERIFIED"    # 409
ERR_LIFETIME_MAX_REACHED = "ERR_LIFETIME_MAX_REACHED"    # 409
ERR_BENEFIT_EXHAUSTED = "ERR_BENEFIT_EXHAUSTED"          # 409
ERR_ENROLLMENT_NOT_FUNDED = "ERR_ENROLLMENT_NOT_FUNDED"  # 409
ERR_ENROLLMENT_NOT_ACTIVE = "ERR_ENROLLMENT_NOT_ACTIVE"  # 409

# --- porting / concurrency ---
ERR_ALREADY_PORTED = "ERR_ALREADY_PORTED"                       # 409
ERR_STALE_ENROLLMENT_VERSION = "ERR_STALE_ENROLLMENT_VERSION"   # 412
ERR_CLAIM_ALREADY_PAID = "ERR_CLAIM_ALREADY_PAID"               # 409

# --- duplicates / field-level ---
ERR_DUPLICATE_ENROLLMENT = "ERR_DUPLICATE_ENROLLMENT"           # 409
ERR_DUPLICATE_PAY_PERIOD = "ERR_DUPLICATE_PAY_PERIOD"           # 409
ERR_DUPLICATE_SCHEDULE_EVENT = "ERR_DUPLICATE_SCHEDULE_EVENT"   # 409
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                     # 422
ERR_VALIDATION_PAGINATION = "ERR_VALIDATION_PAGINATION"         # 422


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- factory helpers (priority order per PRD §2.10) ---

def missing_user_context(msg="Missing or malformed user context"):
    return ApiError(ERR_MISSING_USER_CONTEXT, msg, 401)


def forbidden_role(msg="Role not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN_ROLE, msg, 403)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, msg, 404)


def reference_mismatch(msg="Cross-aggregate reference inconsistent"):
    return ApiError(ERR_REFERENCE_MISMATCH, msg, 409)


def invalid_state(msg="Resource not in a valid state for the requested transition"):
    return ApiError(ERR_INVALID_STATE, msg, 409)


def product_not_open(msg="Plan product is not OPEN"):
    return ApiError(ERR_PRODUCT_NOT_OPEN, msg, 409)


def schedule_empty(msg="Plan product has no benefit-schedule item"):
    return ApiError(ERR_SCHEDULE_EMPTY, msg, 409)


def employee_terminated(msg="Employee is TERMINATED"):
    return ApiError(ERR_EMPLOYEE_TERMINATED, msg, 409)


def section125_inactive(msg="Employer Section 125 plan is not active"):
    return ApiError(ERR_SECTION125_INACTIVE, msg, 409)


def event_before_coverage(msg="Claim event_date before coverage or enrollment not active"):
    return ApiError(ERR_EVENT_BEFORE_COVERAGE, msg, 422)


def event_not_covered(msg="Claim event_code not covered by the enrolled product"):
    return ApiError(ERR_EVENT_NOT_COVERED, msg, 422)


def account_not_verified(msg="Disbursement account is not VERIFIED"):
    return ApiError(ERR_ACCOUNT_NOT_VERIFIED, msg, 409)


def lifetime_max_reached(msg="Lifetime occurrence maximum already reached"):
    return ApiError(ERR_LIFETIME_MAX_REACHED, msg, 409)


def benefit_exhausted(msg="Annual benefit remaining is 0"):
    return ApiError(ERR_BENEFIT_EXHAUSTED, msg, 409)


def enrollment_not_funded(msg="Enrollment funding_status is not CURRENT"):
    return ApiError(ERR_ENROLLMENT_NOT_FUNDED, msg, 409)


def enrollment_not_active(msg="Enrollment lifecycle_status is not ACTIVE"):
    return ApiError(ERR_ENROLLMENT_NOT_ACTIVE, msg, 409)


def already_ported(msg="Enrollment is not TERMINATED or already ported"):
    return ApiError(ERR_ALREADY_PORTED, msg, 409)


def stale_enrollment_version(msg="expected_enrollment_version does not match current version"):
    return ApiError(ERR_STALE_ENROLLMENT_VERSION, msg, 412)


def claim_already_paid(msg="Claim has a SETTLED disbursement"):
    return ApiError(ERR_CLAIM_ALREADY_PAID, msg, 409)


def duplicate_enrollment(msg="Employee already holds a non-terminal enrollment in this product"):
    return ApiError(ERR_DUPLICATE_ENROLLMENT, msg, 409)


def duplicate_pay_period(msg="pay_period_index already recorded for this enrollment"):
    return ApiError(ERR_DUPLICATE_PAY_PERIOD, msg, 409)


def duplicate_schedule_event(msg="event_code already exists on this product"):
    return ApiError(ERR_DUPLICATE_SCHEDULE_EVENT, msg, 409)


def invalid_request(msg="Request body field-level validation failed"):
    return ApiError(ERR_INVALID_REQUEST, msg, 422)


def validation_pagination(msg="limit/offset outside allowed bounds"):
    return ApiError(ERR_VALIDATION_PAGINATION, msg, 422)
