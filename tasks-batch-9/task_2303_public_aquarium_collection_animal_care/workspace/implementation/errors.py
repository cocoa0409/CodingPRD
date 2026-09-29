"""Error catalogue (SCAFFOLD.yaml section 1.6 / PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status=None, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


# error_id -> http status
ERROR_STATUS = {
    # auth
    "ERR_MISSING_USER_CONTEXT": 401,
    "ERR_INVALID_ROLE": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_INSTITUTION_SCOPE_VIOLATION": 403,
    # existence
    "ERR_LIFE_SUPPORT_SYSTEM_NOT_FOUND": 404,
    "ERR_EXHIBIT_NOT_FOUND": 404,
    "ERR_SPECIES_NOT_FOUND": 404,
    "ERR_INSTITUTION_NOT_FOUND": 404,
    "ERR_COLLECTION_PLAN_ENTRY_NOT_FOUND": 404,
    "ERR_ACQUISITION_REQUEST_NOT_FOUND": 404,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_SPECIMEN_NOT_FOUND": 404,
    "ERR_QUARANTINE_CASE_NOT_FOUND": 404,
    "ERR_VETERINARY_CASE_NOT_FOUND": 404,
    "ERR_TRANSFER_REQUEST_NOT_FOUND": 404,
    "ERR_INTERACTION_SESSION_NOT_FOUND": 404,
    "ERR_ACCREDITATION_AUDIT_NOT_FOUND": 404,
    "ERR_WATER_QUALITY_READING_NOT_FOUND": 404,
    "ERR_HUSBANDRY_LOG_NOT_FOUND": 404,
    # schema
    "ERR_VALIDATION": 422,
    "ERR_INVALID_PAGINATION": 400,
    # concurrency
    "ERR_STALE_EXHIBIT_VERSION": 412,
    "ERR_STALE_SPECIES_VERSION": 412,
    # state
    "ERR_INVALID_STATE": 409,
    "ERR_ENTITY_TERMINAL": 409,
    "ERR_INVALID_ACTION": 422,
    # business
    "ERR_SOD_VIOLATION": 409,
    "ERR_SPECIMEN_NOT_HEALTHY": 409,
    "ERR_EXHIBIT_CLOSED": 409,
    "ERR_RESTRICTED_POSTURE_OVERRIDE_REQUIRED": 409,
    "ERR_LIFE_SUPPORT_ALARM": 409,
    "ERR_INTERACTION_PROGRAM_DISABLED": 409,
    "ERR_SAFETY_BRIEFING_REQUIRED": 422,
    "ERR_DIVE_ENCOUNTER_BLOCKED": 409,
    "ERR_QUARANTINE_NOT_COMPLETE": 409,
    "ERR_CLEARANCE_EXAMS_INSUFFICIENT": 409,
    "ERR_TREATMENT_WITHDRAWAL_ACTIVE": 409,
    "ERR_NO_APPROVED_PLAN_ENTRY": 409,
    "ERR_HABITAT_MISMATCH": 422,
    "ERR_PERMIT_NOT_ISSUED": 409,
    "ERR_PERMIT_TYPE_MISMATCH": 422,
    "ERR_RECEIVER_NOT_ELIGIBLE": 409,
    "ERR_MISSING_DOCUMENTS": 422,
    "ERR_TRANSFER_CONDITIONS_INCOMPLETE": 422,
    "ERR_TIMESTAMP_IN_FUTURE": 422,
    "ERR_SESSION_IN_PAST": 422,
    "ERR_INTERVAL_INVALID": 422,
    "ERR_SESSION_BUFFER_CONFLICT": 409,
    "ERR_AUDIT_NOT_DUE": 409,
    "ERR_TRANSFER_DATE_NOT_REACHED": 409,
    "ERR_PERMIT_VALIDITY_TOO_LONG": 422,
    "ERR_GUEST_CAPACITY_EXCEEDED": 422,
    "ERR_ROUND_LIMIT_EXCEEDED": 409,
    "ERR_DUPLICATE_ACTIVE_PLAN_ENTRY": 409,
    "ERR_DUPLICATE_CODE": 409,
    "ERR_JUSTIFICATION_REQUIRED": 422,
    "ERR_SUSTAINABILITY_REQUIREMENT_VIOLATION": 409,
    "ERR_PLANNED_COUNT_EXCEEDED": 409,
    "ERR_BIOLOAD_CAPACITY_EXCEEDED": 409,
    "ERR_QUOTA_EXCEEDED": 409,
    "ERR_CLEARANCE_SCORE_TOO_LOW": 409,
    "ERR_REQUESTED_COUNT_EXCEEDED": 409,
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}

DEFAULT_MESSAGES = {
    "ERR_MISSING_USER_CONTEXT": "Identity headers are absent or empty",
    "ERR_INVALID_ROLE": "The supplied role is not a recognised role name",
    "ERR_UNAUTHORIZED": "The caller's role is not permitted to perform this operation",
    "ERR_INSTITUTION_SCOPE_VIOLATION": "The liaison is scoped to a different institution",
    "ERR_VALIDATION": "Request payload failed schema validation",
    "ERR_INVALID_PAGINATION": "Pagination parameters are out of range",
    "ERR_STALE_EXHIBIT_VERSION": "The supplied exhibit version does not match the stored version",
    "ERR_STALE_SPECIES_VERSION": "The supplied species version does not match the stored version",
    "ERR_INVALID_STATE": "The requested transition is not available from the current state",
    "ERR_ENTITY_TERMINAL": "The entity is already in a terminal state",
    "ERR_INVALID_ACTION": "The requested action is not legal from the current state",
    "ERR_SOD_VIOLATION": "Segregation of duties forbids the same actor performing both steps",
    "ERR_SPECIMEN_NOT_HEALTHY": "The specimen's health status forbids this operation",
    "ERR_EXHIBIT_CLOSED": "The exhibit posture is CLOSED",
    "ERR_RESTRICTED_POSTURE_OVERRIDE_REQUIRED": "An explicit override is required for a RESTRICTED exhibit",
    "ERR_LIFE_SUPPORT_ALARM": "The serving life support system is not in a NORMAL, in-test state",
    "ERR_INTERACTION_PROGRAM_DISABLED": "The exhibit's interaction programme is disabled",
    "ERR_SAFETY_BRIEFING_REQUIRED": "The safety briefing has not been confirmed",
    "ERR_DIVE_ENCOUNTER_BLOCKED": "A dive encounter is blocked by animal health",
    "ERR_QUARANTINE_NOT_COMPLETE": "The quarantine protocol period has not elapsed",
    "ERR_CLEARANCE_EXAMS_INSUFFICIENT": "Not enough clean preventive examinations have been recorded",
    "ERR_TREATMENT_WITHDRAWAL_ACTIVE": "An overlapping treatment withdrawal window is active",
    "ERR_NO_APPROVED_PLAN_ENTRY": "No APPROVED collection plan entry authorises this placement",
    "ERR_HABITAT_MISMATCH": "The exhibit habitat does not match the life support system design habitat",
    "ERR_PERMIT_NOT_ISSUED": "No issued permit covers this operation",
    "ERR_PERMIT_TYPE_MISMATCH": "The permit type does not match what this operation requires",
    "ERR_RECEIVER_NOT_ELIGIBLE": "The receiving institution is not eligible",
    "ERR_MISSING_DOCUMENTS": "Required permit documents are missing",
    "ERR_TRANSFER_CONDITIONS_INCOMPLETE": "Required welfare conditions are missing",
    "ERR_TIMESTAMP_IN_FUTURE": "The supplied timestamp is later than the logical clock",
    "ERR_SESSION_IN_PAST": "The session start is earlier than the logical clock",
    "ERR_INTERVAL_INVALID": "The supplied interval end is not strictly later than its start",
    "ERR_SESSION_BUFFER_CONFLICT": "The session collides with another session inside the buffer",
    "ERR_AUDIT_NOT_DUE": "The audit is not due yet",
    "ERR_TRANSFER_DATE_NOT_REACHED": "The proposed transfer date has not been reached",
    "ERR_PERMIT_VALIDITY_TOO_LONG": "The permit validity span is too long",
    "ERR_GUEST_CAPACITY_EXCEEDED": "The guest count exceeds the maximum",
    "ERR_ROUND_LIMIT_EXCEEDED": "The negotiation or submission round limit is exhausted",
    "ERR_DUPLICATE_ACTIVE_PLAN_ENTRY": "An active plan entry already exists for this exhibit and species",
    "ERR_DUPLICATE_CODE": "The supplied code is already in use",
    "ERR_JUSTIFICATION_REQUIRED": "A justification is required",
    "ERR_SUSTAINABILITY_REQUIREMENT_VIOLATION": "The species rating violates the plan's sustainability requirement",
    "ERR_PLANNED_COUNT_EXCEEDED": "The planned count for this species in this exhibit is exhausted",
    "ERR_BIOLOAD_CAPACITY_EXCEEDED": "The exhibit's bioload capacity would be exceeded",
    "ERR_QUOTA_EXCEEDED": "The annual wild take quota would be exceeded",
    "ERR_CLEARANCE_SCORE_TOO_LOW": "The final sustainability score is below the clearance minimum",
    "ERR_REQUESTED_COUNT_EXCEEDED": "The acquisition request is already fully fulfilled",
    "ERR_NOT_FOUND": "Resource not found",
    "ERR_METHOD_NOT_ALLOWED": "Method not allowed",
    "ERR_INTERNAL": "Internal server error",
}


def not_found(entity_key):
    """entity_key like 'EXHIBIT' -> raises ERR_EXHIBIT_NOT_FOUND."""
    raise ApiError("ERR_%s_NOT_FOUND" % entity_key)
