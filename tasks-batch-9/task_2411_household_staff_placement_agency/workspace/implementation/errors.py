"""Error catalogue for the Household Staff Placement Agency API.

Every identifier and HTTP status below is transcribed from PRD section 5
(Error Catalog).  Nothing else in the implementation may invent an error id.
"""

# error_id -> (http_status, default human readable message)
ERROR_CATALOG = {
    # --- authentication / authorisation -----------------------------------
    "ERR_MISSING_AUTH_HEADER": (401, "X-User-ID and X-User-Role headers are required"),
    "ERR_INVALID_ROLE": (401, "X-User-Role is not one of the seven recognised roles"),
    "ERR_UNAUTHORIZED": (403, "This role is not permitted to perform this operation"),
    "ERR_SEGREGATION_OF_DUTIES": (403, "The acting user may not both create and decide this record"),

    # --- request shape -----------------------------------------------------
    "ERR_INVALID_REQUEST": (400, "A required field is absent, null or malformed"),
    "ERR_INVALID_ENUM": (400, "A field carries a value outside its permitted enumeration"),
    "ERR_INVALID_RANGE": (400, "A numeric field falls outside its accepted band"),
    "ERR_INVALID_DATE_FORMAT": (400, "A date, timestamp or month key is malformed"),
    "ERR_INVALID_INTERVAL": (400, "The interval endpoints are not correctly ordered"),
    "ERR_INVALID_LEDGER_AMOUNT": (400, "A manual ledger adjustment may not be zero"),

    # --- referential resolution -------------------------------------------
    "ERR_CLIENT_NOT_FOUND": (404, "Client not found"),
    "ERR_FEE_SCHEDULE_NOT_FOUND": (404, "Fee schedule not found"),
    "ERR_REQUISITION_NOT_FOUND": (404, "Role requisition not found"),
    "ERR_CANDIDATE_NOT_FOUND": (404, "Candidate not found"),
    "ERR_REFERENCE_CHECK_NOT_FOUND": (404, "Reference check not found"),
    "ERR_BACKGROUND_VERIFICATION_NOT_FOUND": (404, "Background verification not found"),
    "ERR_TRIAL_NOT_FOUND": (404, "Trial engagement not found"),
    "ERR_ACCOMMODATION_TERM_NOT_FOUND": (404, "Accommodation term not found"),
    "ERR_PLACEMENT_NOT_FOUND": (404, "Placement not found"),
    "ERR_FEE_MILESTONE_NOT_FOUND": (404, "Fee milestone not found"),
    "ERR_REPLACEMENT_CLAIM_NOT_FOUND": (404, "Replacement claim not found"),
    "ERR_PAYROLL_HANDOFF_NOT_FOUND": (404, "Payroll handoff not found"),
    "ERR_NON_SOLICITATION_CASE_NOT_FOUND": (404, "Non-solicitation case not found"),
    "ERR_ENTITY_RELATIONSHIP_MISMATCH": (409, "The named rows do not belong together"),

    # --- optimistic concurrency -------------------------------------------
    "ERR_STALE_REQUISITION_VERSION": (412, "expected_requisition_version does not match the stored version"),
    "ERR_STALE_PLACEMENT_VERSION": (412, "expected_placement_version does not match the stored version"),
    "ERR_STALE_CANDIDATE_VERSION": (412, "expected_candidate_version does not match the stored version"),

    # --- state legality ----------------------------------------------------
    "ERR_INVALID_STATE_TRANSITION": (409, "The requested transition is not admissible from the current state"),
    "ERR_ENTITY_TERMINAL": (409, "The row is already in a terminal state"),
    "ERR_REQUISITION_NOT_SCOPING": (409, "The requisition is not in SCOPING"),
    "ERR_TRIAL_NOT_SCHEDULED": (409, "The trial engagement is not SCHEDULED"),
    "ERR_TRIAL_NOT_IN_PROGRESS": (409, "The trial engagement is not IN_PROGRESS"),
    "ERR_BACKGROUND_NOT_FLAGGED": (409, "The background verification is not FLAGGED"),
    "ERR_CLAIM_NOT_UNDER_REVIEW": (409, "The replacement claim is not UNDER_REVIEW"),
    "ERR_MILESTONE_NOT_INVOICED": (409, "The fee milestone is not INVOICED or OVERDUE"),
    "ERR_PLACEMENT_NOT_ACTIVE": (409, "The placement is not in the required state"),
    "ERR_CASE_NOT_INVESTIGATING": (409, "The non-solicitation case is not INVESTIGATING"),

    # --- household eligibility --------------------------------------------
    "ERR_NDA_NOT_COUNTERSIGNED": (409, "The household confidentiality agreement is not countersigned"),
    "ERR_CLIENT_SUSPENDED": (409, "The household is suspended"),
    "ERR_SCOPING_ROUND_LIMIT": (409, "The requisition has exhausted its scoping rounds"),
    "ERR_REQUISITION_HAS_ACTIVE_TRIALS": (409, "The requisition still has active trial engagements"),
    "ERR_NO_FEE_SCHEDULE_MATCH": (422, "No active fee schedule band matches the compensation"),
    "ERR_FEE_BAND_OVERLAP": (409, "The proposed band overlaps an existing active band"),

    # --- candidate eligibility --------------------------------------------
    "ERR_REFERENCE_CHAIN_MISMATCH": (422, "The reference chain is not continuous"),
    "ERR_REFERENCE_PERIOD_OVERLAP": (409, "The employment period overlaps an existing reference"),
    "ERR_CANDIDATE_NOT_VETTED": (409, "The candidate has not reached the required vetting state"),
    "ERR_CANDIDATE_UNAVAILABLE": (409, "The candidate is not available"),
    "ERR_COOLING_OFF_ACTIVE": (409, "The candidate cooling-off period has not elapsed"),
    "ERR_TRIAL_NOT_STARTED": (409, "The trial start instant has not been reached"),
    "ERR_TRIAL_WINDOW_NOT_ELAPSED": (409, "The trial end instant has not been reached"),
    "ERR_TRIAL_OVERLAP": (409, "The proposed trial overlaps another household engagement"),
    "ERR_TRIAL_WEEKLY_CAP_EXCEEDED": (409, "The candidate has reached the weekly trial cap"),
    "ERR_CANDIDATE_SCORE_BELOW_THRESHOLD": (422, "The candidate score is below the required threshold"),
    "ERR_REFERENCE_CHAIN_TOO_SHORT": (422, "The contiguous reference chain is too short for this role"),

    # --- negotiation --------------------------------------------------------
    "ERR_LIVE_IN_INCOMPATIBLE": (409, "The candidate is not willing to live in"),
    "ERR_NEGOTIATION_ROUND_LIMIT": (409, "The negotiation has exhausted its counter rounds"),
    "ERR_RESPONDER_MUST_ALTERNATE": (409, "The same party may not respond twice in a row"),
    "ERR_NO_PASSED_TRIAL": (409, "No passed trial engagement exists for this pairing"),
    "ERR_ACCOMMODATION_NOT_ACCEPTED": (409, "No accepted accommodation term exists for this pairing"),

    # --- billing, remedies, compliance ------------------------------------
    "ERR_CLIENT_CREDIT_HOLD": (409, "The household is over its credit limit"),
    "ERR_PAYROLL_HANDOFF_NOT_ATTESTED": (409, "The payroll handoff has not been attested"),
    "ERR_EIN_NOT_ISSUED": (409, "The employer identification number has not been issued"),
    "ERR_PAYROLL_HANDOFF_EXISTS": (409, "A payroll handoff already exists for this placement"),
    "ERR_PAYMENT_AMOUNT_MISMATCH": (422, "The payment amount does not equal the invoiced amount"),
    "ERR_GUARANTEE_WINDOW_EXPIRED": (409, "The guarantee window has expired"),
    "ERR_INVALID_SEPARATION_DATE": (422, "The separation date is out of bounds"),
    "ERR_OPEN_CLAIM_EXISTS": (409, "An open replacement claim already exists"),
    "ERR_REMEDY_MISMATCH": (409, "The approved remedy does not match the requested remedy"),
    "ERR_NON_SOLICITATION_TERM_EXPIRED": (422, "The non-solicitation term had already expired"),
    "ERR_SETTLEMENT_EXCEEDS_PENALTY": (422, "The settlement exceeds the assessed penalty"),
    "ERR_CLOCK_NOT_MONOTONIC": (422, "The clock may not move backwards"),
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline to abort with a catalogued error."""

    def __init__(self, error_id, message=None):
        status, default_message = ERROR_CATALOG[error_id]
        super().__init__(message or default_message)
        self.error_id = error_id
        self.http_status = status
        self.message = message or default_message


def fail(error_id, message=None):
    raise ApiError(error_id, message)
