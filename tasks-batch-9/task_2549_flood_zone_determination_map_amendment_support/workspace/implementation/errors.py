"""Error catalogue (PRD section 5 / scaffold section 1.6)."""

ERROR_STATUS = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_FOLIO_NOT_OWNED": 403,
    "ERR_BORROWER_NOT_ON_LOAN": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_COMMUNITY_NOT_FOUND": 404,
    "ERR_LENDER_NOT_FOUND": 404,
    "ERR_MAP_PANEL_NOT_FOUND": 404,
    "ERR_PROPERTY_NOT_FOUND": 404,
    "ERR_STRUCTURE_NOT_FOUND": 404,
    "ERR_LOAN_FOLIO_NOT_FOUND": 404,
    "ERR_DETERMINATION_NOT_FOUND": 404,
    "ERR_DISPUTE_NOT_FOUND": 404,
    "ERR_ELEVATION_CERTIFICATE_NOT_FOUND": 404,
    "ERR_MAP_AMENDMENT_REQUEST_NOT_FOUND": 404,
    "ERR_COMPLIANCE_NOTICE_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_LOAN_FOLIO_VERSION": 412,
    # state preconditions
    "ERR_INVALID_PANEL_STATE": 409,
    "ERR_INVALID_DETERMINATION_STATE": 409,
    "ERR_INVALID_DISPUTE_STATE": 409,
    "ERR_INVALID_CERTIFICATE_STATE": 409,
    "ERR_INVALID_AMENDMENT_STATE": 409,
    "ERR_INVALID_NOTICE_STATE": 409,
    "ERR_INVALID_FOLIO_STATE": 409,
    # business: safety / regulatory
    "ERR_COVERAGE_UNAVAILABLE": 409,
    "ERR_NOTICE_PERIOD_NOT_EXPIRED": 409,
    "ERR_FORCE_PLACEMENT_NOT_AUTHORIZED": 403,
    "ERR_MANDATORY_PURCHASE_NOT_TRIGGERED": 409,
    # business: referential
    "ERR_CERTIFICATE_NOT_VALIDATED": 409,
    "ERR_STRUCTURE_FOLIO_MISMATCH": 422,
    "ERR_AMENDMENT_TYPE_MISMATCH": 422,
    "ERR_PROPERTY_NOT_GEOCODED": 422,
    "ERR_NO_EFFECTIVE_PANEL": 422,
    # business: temporal
    "ERR_CERTIFICATE_EXPIRED": 422,
    "ERR_APPEAL_PERIOD_OPEN": 409,
    "ERR_LFD_WAITING_PERIOD": 409,
    "ERR_PANEL_EFFECTIVE_DATE_OVERLAP": 409,
    "ERR_NOTICE_WINDOW_ACTIVE": 409,
    # business: constraint
    "ERR_PANEL_SEQUENCE_INVALID": 409,
    "ERR_RESUBMISSION_LIMIT": 409,
    "ERR_STRUCTURE_NOT_ABOVE_BFE": 422,
    "ERR_DISPUTE_BASIS_UNSUPPORTED": 422,
    "ERR_ORIGINATION_ALREADY_COMPLETE": 409,
    "ERR_PANEL_NOT_PRELIMINARY": 409,
    # business: fiscal
    "ERR_COVERAGE_BELOW_REQUIRED": 422,
    "ERR_ESCROW_INSUFFICIENT": 402,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing, empty or name an unrecognised role.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorised for this operation.",
    "ERR_FOLIO_NOT_OWNED": "The acting lender does not own the target loan folio.",
    "ERR_BORROWER_NOT_ON_LOAN": "The acting borrower is not named on the target loan folio.",
    "ERR_SEGREGATION_OF_DUTIES": "The acting user may not review an artifact they produced.",
    "ERR_INVALID_REQUEST": "The request shape is invalid.",
    "ERR_STALE_LOAN_FOLIO_VERSION": "expected_loan_folio_version does not match the loan folio version.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )


def fail(error_id, message=None):
    raise ApiError(error_id, message)
