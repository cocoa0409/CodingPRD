"""Error catalogue (PRD section 5) for the Residential Earthquake Coverage &
Mitigation Incentive Program API.

Every failure surfaces exactly one error_id from this catalogue together with
the HTTP status the PRD assigns to it.  Names and statuses are transcribed
verbatim from PRD section 5; the rung numbers in the comments are the ladder
positions from PRD section 2.8 (lowest rung wins).
"""


ERROR_STATUS = {
    # --- authentication band (rungs 1-3) ------------------------------------
    "ERR_MISSING_ROLE": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_MISSING_USER_ID": 401,
    # --- existence band (rungs 4-5) -----------------------------------------
    "ERR_POLICYHOLDER_NOT_FOUND": 404,
    "ERR_INSURER_NOT_FOUND": 404,
    "ERR_DWELLING_NOT_FOUND": 404,
    "ERR_OFFER_NOT_FOUND": 404,
    "ERR_POLICY_NOT_FOUND": 404,
    "ERR_GRANT_CYCLE_NOT_FOUND": 404,
    "ERR_GRANT_NOT_FOUND": 404,
    "ERR_CONTRACTOR_NOT_FOUND": 404,
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    "ERR_EVENT_NOT_FOUND": 404,
    "ERR_LAYER_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_ALLOCATION_NOT_FOUND": 404,
    # --- resource-scoped authorization band (rungs 6-9) ---------------------
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SOD_GRANT_REVIEWER_CONFLICT": 403,
    "ERR_SOD_INSPECTOR_CONFLICT": 403,
    "ERR_SOD_ADJUSTER_CONFLICT": 403,
    # --- request-shape band (rungs 10-13) -----------------------------------
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_ENUM_VALUE": 422,
    "ERR_INVALID_AMOUNT": 422,
    "ERR_INVALID_WINDOW": 422,
    # --- optimistic-concurrency band (rungs 14-15) --------------------------
    "ERR_STALE_GRANT_CYCLE_VERSION": 412,
    "ERR_STALE_EVENT_VERSION": 412,
    # --- state-precondition band (rungs 16-34) ------------------------------
    "ERR_OFFER_ALREADY_RESPONDED": 409,
    "ERR_OFFER_NOT_REOFFERABLE": 409,
    "ERR_POLICY_NOT_QUOTED": 409,
    "ERR_POLICY_NOT_ACTIVE": 409,
    "ERR_NO_MITIGATION_DISCOUNT": 409,
    "ERR_GRANT_CYCLE_CLOSED": 409,
    "ERR_GRANT_INVALID_STATE": 409,
    "ERR_PROJECT_INVALID_STATE": 409,
    "ERR_INSPECTION_ALREADY_RECORDED": 409,
    "ERR_EVENT_INVALID_STATE": 409,
    "ERR_EVENT_CLOSED": 409,
    "ERR_EVENT_ASSESSMENT_LOCKED": 409,
    "ERR_EVENT_NOT_DECLARED": 409,
    "ERR_EVENT_CAPACITY_NOT_EXHAUSTED": 409,
    "ERR_EVENT_HAS_OPEN_CLAIMS": 409,
    "ERR_CLAIM_INVALID_STATE": 409,
    "ERR_CLAIM_ALREADY_SETTLED": 409,
    "ERR_CLAIM_REOPEN_LIMIT": 409,
    "ERR_CLAIM_NOT_FULLY_PAID": 409,
    # --- safety and compliance band (rungs 35-44) ---------------------------
    "ERR_INSURER_SANCTIONED": 409,
    "ERR_INSURER_WITHDRAWN": 409,
    "ERR_INSURER_NOT_SANCTIONED": 409,
    "ERR_INSURER_ALREADY_WITHDRAWN": 409,
    "ERR_CONTRACTOR_NOT_CERTIFIED": 409,
    "ERR_CONTRACTOR_CERTIFICATION_EXPIRED": 409,
    "ERR_CONTRACTOR_INVALID_CERTIFICATION_TRANSITION": 409,
    "ERR_RETROFIT_SCOPE_MISMATCH": 409,
    "ERR_MAGNITUDE_BELOW_DECLARATION_FLOOR": 422,
    "ERR_STRUCTURE_NOT_GRANT_ELIGIBLE": 422,
    # --- referential-integrity band (rungs 45-51) ---------------------------
    "ERR_MANDATORY_OFFER_NOT_ACCEPTED": 409,
    "ERR_DWELLING_OWNER_MISMATCH": 422,
    "ERR_GRANT_FUNDS_NOT_RESERVED": 409,
    "ERR_INSPECTION_PROJECT_MISMATCH": 422,
    "ERR_NO_REINSURANCE_PROGRAM": 409,
    "ERR_DUPLICATE_LAYER_INDEX": 409,
    "ERR_LAYER_ATTACHMENT_GAP": 422,
    # --- uniqueness and count band (rungs 52-57) ----------------------------
    "ERR_DUPLICATE_ACTIVE_POLICY": 409,
    "ERR_DUPLICATE_PENDING_OFFER": 409,
    "ERR_DUPLICATE_OPEN_GRANT": 409,
    "ERR_DUPLICATE_CLAIM": 409,
    "ERR_GRANT_REVIEW_ROUNDS_EXHAUSTED": 409,
    "ERR_CONTRACTOR_PROJECT_CAP": 409,
    # --- temporal-conflict band (rungs 58-69) -------------------------------
    "ERR_INSPECTION_DURATION_INVALID": 422,
    "ERR_INSPECTION_IN_PAST": 422,
    "ERR_INSPECTION_SLOT_OVERLAP": 409,
    "ERR_INSPECTION_WINDOW_NOT_REACHED": 409,
    "ERR_GRANT_CYCLE_WINDOW_OVERLAP": 409,
    "ERR_QUOTE_EXPIRED": 409,
    "ERR_QUOTE_STILL_VALID": 409,
    "ERR_OFFER_EXPIRED": 409,
    "ERR_OFFER_STILL_VALID": 409,
    "ERR_RENEWAL_WINDOW_NOT_OPEN": 409,
    "ERR_BINDING_MORATORIUM": 409,
    "ERR_POLICY_NOT_IN_FORCE_AT_EVENT": 409,
    # --- capacity band (rungs 71-72) ----------------------------------------
    "ERR_NO_ASSESSABLE_INSURERS": 409,
    "ERR_GRANT_TIER_CAP_EXHAUSTED": 409,
    # --- fiscal band (rungs 73-75) ------------------------------------------
    "ERR_GRANT_CYCLE_POOL_EXHAUSTED": 409,
    "ERR_SUBLIMIT_EXCEEDS_LIMIT": 422,
    "ERR_PAYMENT_EXCEEDS_PAYABLE": 422,
    # --- rung 76 ------------------------------------------------------------
    "ERR_RETROFIT_ALREADY_VERIFIED": 409,
}


DEFAULT_MESSAGE = {
    "ERR_MISSING_ROLE": "X-User-Role is absent or is not one of the seven declared roles.",
    "ERR_UNAUTHORIZED": "The acting role is not authorised for this operation.",
    "ERR_MISSING_USER_ID": "X-User-ID must be present and non-empty for this operation.",
    "ERR_NOT_RESOURCE_OWNER": "The acting identity does not own the addressed resource.",
    "ERR_INVALID_REQUEST": "A required field is missing, null or malformed.",
    "ERR_INVALID_ENUM_VALUE": "A supplied value lies outside its declared domain.",
    "ERR_INVALID_AMOUNT": "A supplied numeric value lies outside its declared range.",
    "ERR_INVALID_WINDOW": "The supplied interval is empty or inverted.",
}


def message_for(error_id):
    if error_id in DEFAULT_MESSAGE:
        return DEFAULT_MESSAGE[error_id]
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return "Request rejected: " + words + "."


class ApiError(Exception):
    """Carries the error_id, its human-readable message and its HTTP status."""

    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.status = ERROR_STATUS.get(error_id, 400)
        self.message = message if message else message_for(error_id)


def status_for(error_id):
    return ERROR_STATUS.get(error_id, 400)
