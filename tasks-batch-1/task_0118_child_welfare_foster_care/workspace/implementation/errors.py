"""Error catalogue (PRD §5 / SCAFFOLD §1.6).

Every error_id and its HTTP status is taken verbatim from the scaffold error
catalog. The ApiError carries the error_id, a human message, and the HTTP status.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Auth / generic --------------------------------------------------------
def unauthenticated(msg="Missing or malformed authentication headers."):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def unauthorized(msg="Acting role is not permitted to invoke this operation."):
    return ApiError("ERR_UNAUTHORIZED", 403, msg)


def not_found(msg="A referenced resource does not exist."):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_request(msg="Malformed request body."):
    return ApiError("ERR_INVALID_REQUEST", 422, msg)


def invalid_state(msg="Resource is not in a state from which this transition is defined."):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def validation_limit(msg="A numeric input violates its declared range."):
    return ApiError("ERR_VALIDATION_LIMIT", 422, msg)


# --- Domain-specific -------------------------------------------------------
def sod_conflict(msg="Investigator may not equal the referral's screened_in_by (segregation of duties)."):
    return ApiError("ERR_SOD_CONFLICT", 409, msg)


def referral_not_screened_in(msg="Referral is not SCREENED_IN."):
    return ApiError("ERR_REFERRAL_NOT_SCREENED_IN", 409, msg)


def investigation_not_removal(msg="Investigation is not UNSAFE or CONDITIONALLY_SAFE."):
    return ApiError("ERR_INVESTIGATION_NOT_REMOVAL", 409, msg)


def home_not_licensed(msg="Foster home license_status is not LICENSED or PROVISIONAL."):
    return ApiError("ERR_HOME_NOT_LICENSED", 409, msg)


def clearance_flagged(msg="Foster home has a FLAGGED caregiver screening."):
    return ApiError("ERR_CLEARANCE_FLAGGED", 409, msg)


def clearances_incomplete(msg="A caregiver screening is still PENDING."):
    return ApiError("ERR_CLEARANCES_INCOMPLETE", 409, msg)


def age_not_licensed(msg="Child age_years exceeds the foster home's max_age_years."):
    return ApiError("ERR_AGE_NOT_LICENSED", 409, msg)


def no_beds(msg="Foster home has no open bed."):
    return ApiError("ERR_NO_BEDS", 409, msg)


def stale_version(msg="expected_foster_home_version does not match the home's current version."):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def invalid_window(msg="window_end must be strictly after window_start."):
    return ApiError("ERR_INVALID_WINDOW", 422, msg)


def visit_overlap(msg="Visit overlaps an existing scheduled visit for the same child."):
    return ApiError("ERR_VISIT_OVERLAP", 409, msg)


def hearing_overlap(msg="Hearing falls within the docket buffer of an existing scheduled hearing."):
    return ApiError("ERR_HEARING_OVERLAP", 409, msg)


def plan_not_complete(msg="Case plan compliance_pct is below 100."):
    return ApiError("ERR_PLAN_NOT_COMPLETE", 409, msg)


def goal_mismatch(msg="Case permanency_goal does not match the requested action."):
    return ApiError("ERR_GOAL_MISMATCH", 409, msg)


def hearing_prereq_missing(msg="A required HELD hearing of the necessary type does not exist."):
    return ApiError("ERR_HEARING_PREREQ_MISSING", 409, msg)


def age_not_eligible(msg="Child does not meet the age eligibility requirement."):
    return ApiError("ERR_AGE_NOT_ELIGIBLE", 409, msg)


def tpr_not_terminated(msg="No HELD TPR hearing with ruling TERMINATE_RIGHTS."):
    return ApiError("ERR_TPR_NOT_TERMINATED", 409, msg)
