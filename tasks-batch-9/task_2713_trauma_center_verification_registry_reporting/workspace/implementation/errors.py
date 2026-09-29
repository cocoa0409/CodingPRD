"""Error catalog (PRD section 5) and the API exception type."""

ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": (401, "X-User-ID and X-User-Role headers are required"),
    "ERR_ROLE_NOT_PERMITTED": (403, "role is not permitted to perform this operation"),
    "ERR_CENTER_SCOPE_VIOLATION": (403, "TraumaProgramManager may only act inside its own trauma center"),
    "ERR_DESIGNATION_AUTHORITY_MISMATCH": (403, "the deciding authority does not match the cycle type"),
    "ERR_CENTER_NOT_FOUND": (404, "trauma center not found"),
    "ERR_CASE_NOT_FOUND": (404, "registry case not found"),
    "ERR_CYCLE_NOT_FOUND": (404, "verification cycle not found"),
    "ERR_PI_EVENT_NOT_FOUND": (404, "performance improvement event not found"),
    "ERR_REFERENCED_RESOURCE_NOT_FOUND": (404, "referenced resource not found"),
    "ERR_INVALID_REQUEST": (400, "request payload is missing a required field or has an invalid type"),
    "ERR_INVALID_ENUM_VALUE": (422, "value is not a member of the allowed enumeration"),
    "ERR_STALE_CASE_VERSION": (412, "expected_case_version does not match the current registry case version"),
    "ERR_STALE_CYCLE_VERSION": (412, "expected_cycle_version does not match the current verification cycle version"),
    "ERR_CASE_NOT_ABSTRACTABLE": (409, "registry case is not in an abstractable state"),
    "ERR_CASE_ALREADY_LOCKED": (409, "registry case is locked and can no longer be modified"),
    "ERR_TRIAGE_ALREADY_REVIEWED": (409, "triage review has already been adjudicated for this case"),
    "ERR_ABSTRACTION_ALREADY_ADJUDICATED": (409, "abstraction has already been validated or rejected"),
    "ERR_INVALID_CYCLE_STATE": (409, "verification cycle is not in a state that allows this transition"),
    "ERR_INVALID_PI_STATE": (409, "PI event is not in a state that allows this transition"),
    "ERR_INVALID_DEFICIENCY_STATE": (409, "criteria deficiency is not in a state that allows this transition"),
    "ERR_INVALID_ACTION_STATE": (409, "corrective action is not in a state that allows this transition"),
    "ERR_INVALID_AGREEMENT_STATE": (409, "referral agreement is not in a state that allows this transition"),
    "ERR_INVALID_OUTREACH_STATE": (409, "outreach activity is not in a state that allows this transition"),
    "ERR_POSTURE_SUSPENDED": (409, "trauma center readiness posture is SUSPENDED; registry and verification writes are frozen"),
    "ERR_DICTIONARY_CRITICAL_VIOLATION": (422, "abstraction violates a CRITICAL data dictionary rule"),
    "ERR_ABSTRACTION_NOT_VALIDATED": (409, "registry case has no validated abstraction"),
    "ERR_OPEN_ACTIONS_BLOCK_LOOP_CLOSURE": (409, "loop closure requires every corrective action to be VERIFIED"),
    "ERR_CRITICAL_DEFICIENCY_BLOCKS_VERIFICATION": (409, "an open TYPE_I_CRITICAL deficiency blocks this decision"),
    "ERR_NO_ACTIVE_REFERRAL_AGREEMENT": (409, "no ACTIVE referral agreement covers this transfer"),
    "ERR_ABSTRACTION_WINDOW_CLOSED": (422, "the 60 day abstraction window for this case has closed"),
    "ERR_INVALID_INTERVAL_DATES": (422, "interval endpoints are not ordered, or the due date is in the past"),
    "ERR_SEGREGATION_OF_DUTIES": (409, "the acting user may not both perform and adjudicate this step"),
    "ERR_DUPLICATE_CASE_MRN": (409, "a registry case with this MRN already exists for the center"),
    "ERR_DUPLICATE_CONFIGURATION": (409, "this configuration row already exists"),
    "ERR_AGREEMENT_INTERVAL_OVERLAP": (409, "an ACTIVE agreement already covers an overlapping interval for this center pair"),
    "ERR_SURVEYOR_WINDOW_CONFLICT": (409, "surveyor window conflicts with an existing booking once the travel buffer is applied"),
    "ERR_READINESS_BELOW_THRESHOLD": (409, "reviewer readiness score is below the 70.00 submission threshold"),
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super(ApiError, self).__init__(error_id)
        status, default_message = ERROR_CATALOG.get(error_id, (400, "invalid request"))
        self.error_id = error_id
        self.http_status = status
        self.message = message or default_message
