"""Error catalogue (PRD section 5 / SCAFFOLD 1.6) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- authentication / authorization -------------------------------------
def unauthenticated(msg="Missing or unrecognized X-User-Role header."):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden_role(msg="The caller's role may not invoke this endpoint."):
    return ApiError("ERR_FORBIDDEN_ROLE", 403, msg)


def invalid_request(msg="The request payload is invalid."):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def scope_violation(msg="X-User-ID does not own the target resource."):
    return ApiError("ERR_PROVIDER_SCOPE_VIOLATION", 403, msg)


def segregation_of_duties(msg="The proposing auditor may not resolve the adjustment."):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


# --- existence -----------------------------------------------------------
NOT_FOUND_IDS = {
    "Provider": "ERR_PROVIDER_NOT_FOUND",
    "CostReport": "ERR_COST_REPORT_NOT_FOUND",
    "CostCenter": "ERR_COST_CENTER_NOT_FOUND",
    "TrialBalanceLine": "ERR_TRIAL_BALANCE_LINE_NOT_FOUND",
    "WorkpaperEntry": "ERR_WORKPAPER_ENTRY_NOT_FOUND",
    "StepdownRun": "ERR_STEPDOWN_RUN_NOT_FOUND",
    "WageIndexSubmission": "ERR_WAGE_INDEX_SUBMISSION_NOT_FOUND",
    "OccMixResponse": "ERR_OCC_MIX_RESPONSE_NOT_FOUND",
    "Resident": "ERR_RESIDENT_NOT_FOUND",
    "RotationAssignment": "ERR_ROTATION_ASSIGNMENT_NOT_FOUND",
    "UccDataSet": "ERR_UCC_DATA_SET_NOT_FOUND",
    "Settlement": "ERR_SETTLEMENT_NOT_FOUND",
    "AuditAdjustment": "ERR_AUDIT_ADJUSTMENT_NOT_FOUND",
    "AppealCase": "ERR_APPEAL_CASE_NOT_FOUND",
    "InterimRateRequest": "ERR_INTERIM_RATE_REQUEST_NOT_FOUND",
}


def not_found(entity):
    return ApiError(NOT_FOUND_IDS[entity], 404, "%s not found." % entity)


def referenced_not_found(msg="A referenced entity does not exist."):
    return ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", 404, msg)


# --- concurrency ---------------------------------------------------------
def stale_cost_report_version():
    return ApiError(
        "ERR_STALE_COST_REPORT_VERSION", 412,
        "expected_cost_report_version does not match the cost report's version.")


def stale_provider_version():
    return ApiError(
        "ERR_STALE_PROVIDER_VERSION", 412,
        "expected_provider_version does not match the provider's version.")


# --- state ---------------------------------------------------------------
def invalid_state(msg="The requested transition is not available from the current state."):
    return ApiError("ERR_INVALID_STATE_TRANSITION", 409, msg)


def not_editable(msg="The cost report is not in DRAFT or REOPENED."):
    return ApiError("ERR_COST_REPORT_NOT_EDITABLE", 409, msg)


def business(error_id, msg=None, status=422):
    return ApiError(error_id, status, msg or error_id)
