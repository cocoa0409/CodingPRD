"""Error catalogue (PRD section 5) and the exception type carried through the stack."""

ERROR_STATUS = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_MANAGER_APPROVAL_REQUIRED": 403,
    # not found
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_POLICY_NOT_FOUND": 404,
    "ERR_COVERAGE_PART_NOT_FOUND": 404,
    "ERR_INTEREST_NOT_FOUND": 404,
    "ERR_ENDORSEMENT_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_PAYMENT_NOT_FOUND": 404,
    "ERR_NOTICE_NOT_FOUND": 404,
    "ERR_FACILITY_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    # schema
    "ERR_INVALID_REQUEST": 400,
    # optimistic concurrency
    "ERR_STALE_PROJECT_VERSION": 412,
    "ERR_STALE_POLICY_VERSION": 412,
    "ERR_STALE_CLAIM_VERSION": 412,
    # state
    "ERR_INVALID_PROJECT_STATE": 409,
    "ERR_INVALID_POLICY_STATE": 409,
    "ERR_INVALID_CLAIM_STATE": 409,
    "ERR_INVALID_ENDORSEMENT_STATE": 409,
    "ERR_INVALID_NOTICE_STATE": 409,
    "ERR_INVALID_ASSIGNMENT_STATE": 409,
    "ERR_INVALID_PAYMENT_STATE": 409,
    "ERR_INVALID_INTEREST_STATE": 409,
    "ERR_RESUBMISSION_LIMIT_REACHED": 409,
    "ERR_REOPEN_LIMIT_REACHED": 409,
    "ERR_FACILITY_SUSPENDED": 409,
    # safety / compliance
    "ERR_ACTIVE_POLICY_EXISTS": 409,
    "ERR_EXISTING_STRUCTURE_NOT_APPLICABLE": 422,
    "ERR_COVERAGE_PART_NOT_PERMITTED": 422,
    "ERR_MITIGATION_PLAN_REQUIRED": 422,
    "ERR_INTERESTS_NOT_ACKNOWLEDGED": 409,
    # temporal
    "ERR_DATE_RANGE_INVALID": 422,
    "ERR_TESTING_WINDOW_CONFLICT": 409,
    "ERR_WINDOW_OUTSIDE_POLICY_TERM": 422,
    "ERR_LOSS_DATE_OUTSIDE_TERM": 422,
    "ERR_CANCEL_DATE_INVALID": 422,
    "ERR_REVISED_DATE_MISMATCH": 422,
    # constraint
    "ERR_DUPLICATE_SITE_CODE": 409,
    "ERR_DUPLICATE_COVERAGE_PART": 409,
    "ERR_SUBLIMIT_EXCEEDS_LIMIT": 422,
    "ERR_INTEREST_PCT_EXCEEDED": 422,
    "ERR_DUPLICATE_PAYEE_PRIORITY": 409,
    "ERR_FACILITY_TOO_DISTANT": 422,
    "ERR_EXTENSION_LIMIT_EXCEEDED": 422,
    "ERR_DUPLICATE_LOSS_ITEM": 422,
    # referential
    "ERR_COVERAGE_PART_MISSING": 422,
    "ERR_PROJECT_NOT_COMPLETE": 422,
    "ERR_TESTING_NOTICE_REQUIRED": 422,
    "ERR_STORAGE_NOT_APPROVED": 422,
    "ERR_PAYEE_NOT_ON_POLICY": 422,
    "ERR_PAYMENT_PART_NOT_ALLOCATED": 422,
    # fiscal
    "ERR_FACILITY_CAPACITY_EXCEEDED": 422,
    "ERR_PAYMENT_EXCEEDS_ALLOCATION": 422,
    "ERR_PAYMENT_EXCEEDS_RESERVE": 422,
    # transport-level fallback (not part of the PRD catalogue)
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return "Request rejected: %s." % words
