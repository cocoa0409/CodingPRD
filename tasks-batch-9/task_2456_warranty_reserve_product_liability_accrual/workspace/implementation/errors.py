"""Error catalogue (PRD §5 / SCAFFOLD §1.6)."""

ERROR_STATUS = {
    # auth / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_SUPPLIER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_PERIOD_NOT_FOUND": 404,
    "ERR_FAMILY_NOT_FOUND": 404,
    "ERR_VINTAGE_NOT_FOUND": 404,
    "ERR_FAILURE_MODE_NOT_FOUND": 404,
    "ERR_CLAIM_OBSERVATION_NOT_FOUND": 404,
    "ERR_ACCRUAL_NOT_FOUND": 404,
    "ERR_ADEQUACY_REVIEW_NOT_FOUND": 404,
    "ERR_FIELD_ACTION_NOT_FOUND": 404,
    "ERR_REMEDY_OPTION_NOT_FOUND": 404,
    "ERR_SERVICE_CONTRACT_NOT_FOUND": 404,
    "ERR_SUPPLIER_NOT_FOUND": 404,
    "ERR_RECOVERY_NOT_FOUND": 404,
    "ERR_LIABILITY_RESERVE_NOT_FOUND": 404,
    "ERR_ROLLFORWARD_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_PERIOD_VERSION": 412,
    "ERR_STALE_FIELD_ACTION_VERSION": 412,
    # state
    "ERR_PERIOD_CLOSED": 409,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_UNPOSTED_ACCRUALS_REMAIN": 409,
    "ERR_ROLLFORWARD_MISSING": 409,
    "ERR_LIABILITY_RESERVE_NOT_BOOKED": 409,
    "ERR_EXECUTION_BEFORE_APPROVAL": 409,
    # safety / compliance
    "ERR_SAFETY_REMEDY_REQUIRED": 422,
    "ERR_REGULATORY_NOTICE_MISSING": 422,
    # referential
    "ERR_SELF_ANALOG_REFERENCE": 422,
    "ERR_REMEDY_OPTION_MISMATCH": 422,
    "ERR_NO_FAILURE_MODES_DEFINED": 422,
    "ERR_ANALOG_BASIS_MISSING": 422,
    "ERR_FIELD_ACTION_NOT_APPROVED": 422,
    # business constraints
    "ERR_DUPLICATE_CODE": 409,
    "ERR_INSUFFICIENT_CLAIM_HISTORY": 422,
    "ERR_VINTAGE_EXPOSURE_EXPIRED": 422,
    "ERR_DUPLICATE_ACCRUAL": 409,
    "ERR_DUPLICATE_LIABILITY_RESERVE": 409,
    "ERR_SUPPLIER_IMPAIRED": 422,
    "ERR_NO_ELIGIBLE_REMEDY_OPTION": 422,
    "ERR_NO_OPEN_PERIOD": 422,
    "ERR_NO_EXPECTED_BASE": 422,
    # temporal
    "ERR_OBSERVATION_WINDOW_OVERLAP": 409,
    "ERR_FIELD_ACTION_WINDOW_CONFLICT": 409,
    "ERR_CONTRACT_PRECEDES_LAUNCH": 422,
    # fiscal
    "ERR_SETTLEMENT_EXCEEDS_ASSERTED": 422,
    "ERR_RESERVE_CAP_EXCEEDED": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or invalid X-User-ID / X-User-Role headers.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorised for this endpoint.",
    "ERR_SUPPLIER_SCOPE_VIOLATION": "A SupplierRep may only act within its own supplier scope.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this operator from performing this action.",
    "ERR_INVALID_REQUEST": "The request payload is malformed.",
    "ERR_PERIOD_NOT_FOUND": "Accrual period not found.",
    "ERR_FAMILY_NOT_FOUND": "Product family not found.",
    "ERR_VINTAGE_NOT_FOUND": "Production vintage not found.",
    "ERR_FAILURE_MODE_NOT_FOUND": "Failure mode not found.",
    "ERR_CLAIM_OBSERVATION_NOT_FOUND": "Claim observation not found.",
    "ERR_ACCRUAL_NOT_FOUND": "Warranty accrual not found.",
    "ERR_ADEQUACY_REVIEW_NOT_FOUND": "Adequacy review not found.",
    "ERR_FIELD_ACTION_NOT_FOUND": "Field action not found.",
    "ERR_REMEDY_OPTION_NOT_FOUND": "Remedy option not found.",
    "ERR_SERVICE_CONTRACT_NOT_FOUND": "Service contract not found.",
    "ERR_SUPPLIER_NOT_FOUND": "Supplier not found.",
    "ERR_RECOVERY_NOT_FOUND": "Supplier recovery not found.",
    "ERR_LIABILITY_RESERVE_NOT_FOUND": "Liability reserve not found.",
    "ERR_ROLLFORWARD_NOT_FOUND": "Rollforward snapshot not found.",
    "ERR_STALE_PERIOD_VERSION": "expected_period_version does not match the current period version.",
    "ERR_STALE_FIELD_ACTION_VERSION": "expected_field_action_version does not match the current field action version.",
    "ERR_PERIOD_CLOSED": "The accrual period scoping this mutation is closed.",
    "ERR_INVALID_STATE_TRANSITION": "The requested transition is not declared from the current state.",
    "ERR_UNPOSTED_ACCRUALS_REMAIN": "A DRAFT or PROPOSED warranty accrual remains in the period.",
    "ERR_ROLLFORWARD_MISSING": "The period has no generated rollforward disclosure.",
    "ERR_LIABILITY_RESERVE_NOT_BOOKED": "A liability reserve of the period is not BOOKED.",
    "ERR_EXECUTION_BEFORE_APPROVAL": "The field action must be APPROVED before execution may start.",
    "ERR_SAFETY_REMEDY_REQUIRED": "A safety recall requires a PERMANENT_REPAIR remedy.",
    "ERR_REGULATORY_NOTICE_MISSING": "The regulatory notice must be filed before approving a safety recall.",
    "ERR_SELF_ANALOG_REFERENCE": "analog_family_id may not reference the family being updated.",
    "ERR_REMEDY_OPTION_MISMATCH": "The remedy option belongs to a different field action.",
    "ERR_NO_FAILURE_MODES_DEFINED": "The vintage's family has no failure mode on file.",
    "ERR_ANALOG_BASIS_MISSING": "ANALOG_BLEND requires analog_family_id and engineering_estimate_rate_ppm.",
    "ERR_FIELD_ACTION_NOT_APPROVED": "The linked field action is not APPROVED.",
    "ERR_DUPLICATE_CODE": "The code already exists within its uniqueness scope.",
    "ERR_INSUFFICIENT_CLAIM_HISTORY": "HISTORICAL_RATE requires a MATURE family history.",
    "ERR_VINTAGE_EXPOSURE_EXPIRED": "The vintage's warranty exposure has expired.",
    "ERR_DUPLICATE_ACCRUAL": "A DRAFT or PROPOSED accrual already exists for this period and vintage.",
    "ERR_DUPLICATE_LIABILITY_RESERVE": "A liability reserve already exists for this period and family.",
    "ERR_SUPPLIER_IMPAIRED": "The supplier's collectability rating is IMPAIRED.",
    "ERR_NO_ELIGIBLE_REMEDY_OPTION": "No eligible remedy option was found.",
    "ERR_NO_OPEN_PERIOD": "No accrual period is OPEN or ANALYSIS_LOCKED.",
    "ERR_NO_EXPECTED_BASE": "The adequacy analysis has no expected-to-date base.",
    "ERR_OBSERVATION_WINDOW_OVERLAP": "The development bucket overlaps an existing observation.",
    "ERR_FIELD_ACTION_WINDOW_CONFLICT": "The affected build window conflicts with an existing field action.",
    "ERR_CONTRACT_PRECEDES_LAUNCH": "sold_date precedes the covered family's launch_date.",
    "ERR_SETTLEMENT_EXCEEDS_ASSERTED": "settled_amount_cents exceeds asserted_amount_cents.",
    "ERR_RESERVE_CAP_EXCEEDED": "Posting this accrual would exceed the family's reserve cap.",
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline; converted to the error envelope."""

    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
