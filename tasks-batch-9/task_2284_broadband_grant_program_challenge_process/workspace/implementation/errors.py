"""Error catalog (PRD section 5 / scaffold errors table)."""

ERROR_STATUS = {
    # auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    # existence
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_LOCATION_NOT_FOUND": 404,
    "ERR_CHALLENGE_NOT_FOUND": 404,
    "ERR_SUBGRANTEE_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_AWARD_NOT_FOUND": 404,
    "ERR_MILESTONE_NOT_FOUND": 404,
    "ERR_AUDIT_NOT_FOUND": 404,
    "ERR_ENVIRONMENTAL_REVIEW_NOT_FOUND": 404,
    # ownership / separation of duties
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # state
    "ERR_PROGRAM_STATE_INVALID": 409,
    "ERR_CHALLENGE_STATE_INVALID": 409,
    "ERR_SUBGRANTEE_STATE_INVALID": 409,
    "ERR_APPLICATION_STATE_INVALID": 409,
    "ERR_APPLICATION_NOT_SELECTED": 409,
    "ERR_AWARD_STATE_INVALID": 409,
    "ERR_MILESTONE_STATE_INVALID": 409,
    "ERR_AUDIT_STATE_INVALID": 409,
    "ERR_EHP_STATE_INVALID": 409,
    "ERR_SCORING_POSTURE_RESTRICTED": 409,
    # concurrency
    "ERR_STALE_CHALLENGE_VERSION": 412,
    "ERR_STALE_APPLICATION_VERSION": 412,
    # environmental
    "ERR_EHP_NOT_CLEARED": 409,
    "ERR_EHP_ADVERSE_EFFECT_BLOCKING": 422,
    # scope
    "ERR_LOCATION_NOT_IN_AWARD_SCOPE": 422,
    "ERR_PROGRAM_SCOPE_MISMATCH": 422,
    # windows
    "ERR_CHALLENGE_WINDOW_CLOSED": 409,
    "ERR_APPLICATION_WINDOW_CLOSED": 409,
    "ERR_REBUTTAL_DEADLINE_NOT_REACHED": 409,
    "ERR_AUDIT_WINDOW_BUFFER_CONFLICT": 409,
    "ERR_LOCATION_CLAIM_WINDOW_CONFLICT": 409,
    "ERR_WINDOW_ORDER_INVALID": 400,
    # business rules
    "ERR_DUPLICATE_CHALLENGE": 409,
    "ERR_EVIDENCE_STANDARD_NOT_MET": 422,
    "ERR_REBUTTAL_PREVAILS": 422,
    "ERR_REBUTTAL_ROUND_EXHAUSTED": 409,
    "ERR_RESUBMISSION_LIMIT_REACHED": 409,
    "ERR_SPEED_COMMITMENT_BELOW_MINIMUM": 422,
    "ERR_MATCH_BELOW_MINIMUM": 422,
    "ERR_SUBGRANTEE_NOT_QUALIFIED": 409,
    "ERR_NO_ELIGIBLE_LOCATIONS": 422,
    "ERR_DUPLICATE_LOCATION_ADDRESS": 409,
    "ERR_AWARD_ALREADY_EXISTS": 409,
    "ERR_FINAL_MILESTONE_CONFLICT": 409,
    # fiscal
    "ERR_ALL_LOCATIONS_EHCL_DEFERRED": 422,
    "ERR_PROGRAM_FUNDS_EXHAUSTED": 422,
    "ERR_NO_DISBURSABLE_AMOUNT": 422,
    "ERR_CLAWBACK_AMOUNT_INVALID": 422,
    # fallback
    "ERR_INTERNAL": 500,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication header X-User-ID is missing or empty.",
    "ERR_UNAUTHORIZED": "The caller role is missing, unknown or not permitted for this operation.",
    "ERR_INVALID_REQUEST": "The request body is malformed or a field failed validation.",
    "ERR_INVALID_PAGINATION": "Pagination parameters are out of range.",
    "ERR_PROGRAM_NOT_FOUND": "Grant program not found.",
    "ERR_LOCATION_NOT_FOUND": "Eligible location not found.",
    "ERR_CHALLENGE_NOT_FOUND": "Challenge not found.",
    "ERR_SUBGRANTEE_NOT_FOUND": "Subgrantee not found.",
    "ERR_APPLICATION_NOT_FOUND": "Application not found.",
    "ERR_AWARD_NOT_FOUND": "Award not found.",
    "ERR_MILESTONE_NOT_FOUND": "Milestone not found.",
    "ERR_AUDIT_NOT_FOUND": "Compliance audit not found.",
    "ERR_ENVIRONMENTAL_REVIEW_NOT_FOUND": "Environmental review not found for this award.",
    "ERR_NOT_RESOURCE_OWNER": "The caller does not own the target resource.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this caller from performing this action.",
    "ERR_PROGRAM_STATE_INVALID": "The program state does not permit this operation.",
    "ERR_CHALLENGE_STATE_INVALID": "The challenge state does not permit the requested transition.",
    "ERR_SUBGRANTEE_STATE_INVALID": "The subgrantee capability state does not permit the requested transition.",
    "ERR_APPLICATION_STATE_INVALID": "The application state does not permit the requested transition.",
    "ERR_APPLICATION_NOT_SELECTED": "The application is not in SELECTED state.",
    "ERR_AWARD_STATE_INVALID": "The award state does not permit the requested transition.",
    "ERR_MILESTONE_STATE_INVALID": "The milestone state does not permit the requested transition.",
    "ERR_AUDIT_STATE_INVALID": "The audit state does not permit the requested transition.",
    "ERR_EHP_STATE_INVALID": "The environmental review state does not permit the requested transition.",
    "ERR_SCORING_POSTURE_RESTRICTED": "The program scoring posture is not OPEN.",
    "ERR_STALE_CHALLENGE_VERSION": "expected_challenge_version does not match the stored challenge version.",
    "ERR_STALE_APPLICATION_VERSION": "expected_application_version does not match the stored application version.",
    "ERR_EHP_NOT_CLEARED": "The environmental review has not been cleared.",
    "ERR_EHP_ADVERSE_EFFECT_BLOCKING": "The environmental review is blocked by an adverse effect finding.",
    "ERR_LOCATION_NOT_IN_AWARD_SCOPE": "A referenced location is not within the award scope.",
    "ERR_PROGRAM_SCOPE_MISMATCH": "The referenced location belongs to a different grant program.",
    "ERR_CHALLENGE_WINDOW_CLOSED": "The challenge window is not open at the current logical time.",
    "ERR_APPLICATION_WINDOW_CLOSED": "The application window is not open at the current logical time.",
    "ERR_REBUTTAL_DEADLINE_NOT_REACHED": "The rebuttal deadline has not been reached and no rebuttal evidence exists.",
    "ERR_AUDIT_WINDOW_BUFFER_CONFLICT": "The audit window overlaps or sits within the buffer of another audit window.",
    "ERR_LOCATION_CLAIM_WINDOW_CONFLICT": "Another active claim on this location overlaps the proposed construction window.",
    "ERR_WINDOW_ORDER_INVALID": "The supplied window boundaries are out of order.",
    "ERR_DUPLICATE_CHALLENGE": "This challenger already has an open challenge on this location.",
    "ERR_EVIDENCE_STANDARD_NOT_MET": "The applicable evidence standard is not met.",
    "ERR_REBUTTAL_PREVAILS": "The rebuttal evidence is at least as strong as the challenge evidence.",
    "ERR_REBUTTAL_ROUND_EXHAUSTED": "The maximum number of rebuttal rounds has been reached.",
    "ERR_RESUBMISSION_LIMIT_REACHED": "The resubmission limit has been reached.",
    "ERR_SPEED_COMMITMENT_BELOW_MINIMUM": "The committed speeds are below the required minimum.",
    "ERR_MATCH_BELOW_MINIMUM": "The offered match is below the program minimum.",
    "ERR_SUBGRANTEE_NOT_QUALIFIED": "The subgrantee is not QUALIFIED.",
    "ERR_NO_ELIGIBLE_LOCATIONS": "The application has no eligible location claims.",
    "ERR_DUPLICATE_LOCATION_ADDRESS": "The location is already recorded in this scope.",
    "ERR_AWARD_ALREADY_EXISTS": "An award already exists for this application or location.",
    "ERR_FINAL_MILESTONE_CONFLICT": "Final milestone conflict.",
    "ERR_ALL_LOCATIONS_EHCL_DEFERRED": "Every claimed location was deferred as extremely high cost.",
    "ERR_PROGRAM_FUNDS_EXHAUSTED": "The program has insufficient uncommitted funds.",
    "ERR_NO_DISBURSABLE_AMOUNT": "The computed payable amount is not positive.",
    "ERR_CLAWBACK_AMOUNT_INVALID": "The clawback settlement amount is invalid.",
    "ERR_INTERNAL": "Internal server error.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)
        self.status = status or ERROR_STATUS.get(error_id, 400)
