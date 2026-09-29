"""Error catalogue (PRD 5) and the exception type used to signal a rung failure."""

ERROR_STATUS = {
    # --- auth / authz -------------------------------------------------------
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    # --- request shape -----------------------------------------------------
    "ERR_INVALID_REQUEST": 400,
    # --- existence ---------------------------------------------------------
    "ERR_BROKER_NOT_FOUND": 404,
    "ERR_STATE_PROGRAM_NOT_FOUND": 404,
    "ERR_CARRIER_NOT_FOUND": 404,
    "ERR_CARRIER_ELIGIBILITY_NOT_FOUND": 404,
    "ERR_MARKET_SECURITY_REVIEW_NOT_FOUND": 404,
    "ERR_PLACEMENT_NOT_FOUND": 404,
    "ERR_DECLINATION_NOT_FOUND": 404,
    "ERR_POLICY_NOT_FOUND": 404,
    "ERR_ENDORSEMENT_NOT_FOUND": 404,
    "ERR_CANCELLATION_NOT_FOUND": 404,
    "ERR_TAX_FILING_LINE_NOT_FOUND": 404,
    "ERR_FILING_BATCH_NOT_FOUND": 404,
    "ERR_AFFIDAVIT_NOT_FOUND": 404,
    # --- optimistic concurrency -------------------------------------------
    "ERR_STALE_PLACEMENT_VERSION": 412,
    "ERR_STALE_POLICY_VERSION": 412,
    "ERR_STALE_CARRIER_VERSION": 412,
    # --- state -------------------------------------------------------------
    "ERR_INVALID_STATE": 409,
    "ERR_PLACEMENT_NOT_BINDABLE": 409,
    "ERR_PLACEMENT_ALREADY_BOUND": 409,
    "ERR_POLICY_NOT_ISSUED": 409,
    "ERR_TAX_NOT_CALCULATED": 409,
    "ERR_NOTICES_NOT_AFFIXED": 409,
    "ERR_REVIEW_ALREADY_OPEN": 409,
    "ERR_BROKER_SUSPENDED": 409,
    "ERR_BATCH_EMPTY": 409,
    "ERR_ENDORSEMENT_ALREADY_REMITTED": 409,
    # --- segregation of duties / licensing --------------------------------
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_BROKER_LICENSE_NOT_ACTIVE": 409,
    # --- carrier eligibility ----------------------------------------------
    "ERR_CARRIER_NOT_SECURITY_APPROVED": 409,
    "ERR_CARRIER_NOT_WHITE_LISTED": 409,
    "ERR_CARRIER_BELOW_STATE_CAPITAL_MINIMUM": 409,
    # --- interval collisions ----------------------------------------------
    "ERR_POLICY_TERM_OVERLAP": 409,
    "ERR_ELIGIBILITY_WINDOW_CONFLICT": 409,
    # --- uniqueness --------------------------------------------------------
    "ERR_STATE_PROGRAM_DUPLICATE": 409,
    "ERR_CARRIER_DUPLICATE": 409,
    # --- fiscal / documentary ---------------------------------------------
    "ERR_HOME_STATE_INDETERMINATE": 422,
    "ERR_DILIGENT_SEARCH_INSUFFICIENT": 422,
    "ERR_ALLOCATION_STATE_PROGRAM_MISSING": 422,
    "ERR_NOTICES_INCOMPLETE": 422,
    "ERR_AFFIDAVIT_COUNT_MISMATCH": 422,
    "ERR_DECISION_SCORE_MISMATCH": 422,
    "ERR_CONDITIONS_NOTE_REQUIRED": 422,
    "ERR_REJECTION_REASON_REQUIRED": 422,
    "ERR_SUPERSEDE_TARGET_INVALID": 422,
    "ERR_PREMIUM_WOULD_BE_NON_POSITIVE": 422,
    "ERR_CANCELLATION_DATE_OUT_OF_TERM": 422,
    "ERR_FLAT_CANCELLATION_NOT_AVAILABLE": 422,
    "ERR_PERIOD_KEY_MALFORMED": 422,
    "ERR_REMITTANCE_AMOUNT_MISMATCH": 422,
}

# Entity -> its 404 error id (PRD 2.9: one error per entity).
NOT_FOUND_ERROR = {
    "broker": "ERR_BROKER_NOT_FOUND",
    "state_program": "ERR_STATE_PROGRAM_NOT_FOUND",
    "carrier": "ERR_CARRIER_NOT_FOUND",
    "carrier_eligibility": "ERR_CARRIER_ELIGIBILITY_NOT_FOUND",
    "market_security_review": "ERR_MARKET_SECURITY_REVIEW_NOT_FOUND",
    "placement": "ERR_PLACEMENT_NOT_FOUND",
    "declination": "ERR_DECLINATION_NOT_FOUND",
    "policy": "ERR_POLICY_NOT_FOUND",
    "endorsement": "ERR_ENDORSEMENT_NOT_FOUND",
    "cancellation": "ERR_CANCELLATION_NOT_FOUND",
    "tax_filing_line": "ERR_TAX_FILING_LINE_NOT_FOUND",
    "filing_batch": "ERR_FILING_BATCH_NOT_FOUND",
    "affidavit": "ERR_AFFIDAVIT_NOT_FOUND",
}


class ApiError(Exception):
    """Raised anywhere in the ladder; converted into the error envelope."""

    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    body = error_id[4:] if error_id.startswith("ERR_") else error_id
    return body.replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)


def not_found(entity_key):
    raise ApiError(NOT_FOUND_ERROR[entity_key])
