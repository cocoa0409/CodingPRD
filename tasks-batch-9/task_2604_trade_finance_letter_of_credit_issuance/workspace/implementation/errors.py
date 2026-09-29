"""Error catalogue (SCAFFOLD.yaml 1.6 / PRD 5) -- 68 error ids."""

ERROR_CATALOG = {
    # ---- authentication / authorization ----
    "ERR_UNAUTHENTICATED": (401, "Authentication headers are required"),
    "ERR_UNAUTHORIZED": (403, "Role is not permitted to perform this operation"),
    "ERR_PRINCIPAL_NOT_PARTY": (403, "The acting principal is not a party to this instrument"),
    "ERR_SEGREGATION_OF_DUTIES": (403, "The same user cannot both prepare and approve this step"),
    # ---- shape ----
    "ERR_INVALID_REQUEST": (422, "Request payload is invalid"),
    # ---- existence ----
    "ERR_APPLICANT_NOT_FOUND": (404, "Applicant not found"),
    "ERR_FACILITY_NOT_FOUND": (404, "Credit facility not found"),
    "ERR_BANK_NOT_FOUND": (404, "Bank not found"),
    "ERR_BENEFICIARY_NOT_FOUND": (404, "Beneficiary not found"),
    "ERR_CREDIT_NOT_FOUND": (404, "Documentary credit not found"),
    "ERR_AMENDMENT_NOT_FOUND": (404, "Amendment not found"),
    "ERR_PRESENTATION_NOT_FOUND": (404, "Presentation not found"),
    "ERR_WAIVER_REQUEST_NOT_FOUND": (404, "Waiver request not found"),
    "ERR_SETTLEMENT_CLAIM_NOT_FOUND": (404, "Settlement claim not found"),
    "ERR_SCREENING_CHECK_NOT_FOUND": (404, "Screening check not found"),
    # ---- state preconditions ----
    "ERR_CREDIT_NOT_DRAFT": (409, "Credit terms can only be edited while the credit is a draft"),
    "ERR_CREDIT_NOT_APPROVED": (409, "Credit must be approved before it can be issued"),
    "ERR_CREDIT_NOT_ISSUED": (409, "Operation requires an issued credit"),
    "ERR_CREDIT_TERMINAL": (409, "Credit is in a terminal state"),
    "ERR_CREDIT_HAS_LIVE_PRESENTATION": (409, "Credit cannot be cancelled while a presentation is live"),
    "ERR_AMENDMENT_NOT_DRAFT": (409, "Amendment has already been issued"),
    "ERR_AMENDMENT_NOT_PENDING_CONSENT": (409, "Amendment is not awaiting beneficiary consent"),
    "ERR_PRESENTATION_NOT_EXAMINABLE": (409, "Presentation is not in an examinable state"),
    "ERR_PRESENTATION_ALREADY_CONCLUDED": (409, "Examination has already been concluded for this presentation"),
    "ERR_PRESENTATION_NOT_COMPLYING": (409, "A claim can only be lodged against complying documents"),
    "ERR_WAIVER_NOT_PENDING": (409, "Waiver request is no longer pending"),
    "ERR_WAIVER_RESPONSE_PENDING": (409, "A waiver response is still awaited"),
    "ERR_CLAIM_NOT_LODGED": (409, "Settlement claim is not in a settleable state"),
    "ERR_FACILITY_NOT_ACTIVE": (409, "Credit facility is not active"),
    "ERR_FACILITY_STILL_RESTRICTED": (409, "Facility cannot be reactivated while it remains over the restriction threshold"),
    "ERR_FACILITY_HAS_OPEN_ALLOCATION": (409, "Facility cannot be closed while allocations remain open"),
    "ERR_SCREENING_NOT_REVIEWABLE": (409, "Only a pending screening hit can be reviewed"),
    # ---- concurrency ----
    "ERR_STALE_CREDIT_VERSION": (412, "Credit has been modified since it was read"),
    "ERR_STALE_FACILITY_VERSION": (412, "Credit facility has been modified since it was read"),
    # ---- business safety ----
    "ERR_SANCTIONS_BLOCK": (403, "Operation is blocked by sanctions screening"),
    "ERR_SCREENING_REVIEW_PENDING": (409, "A screening hit is awaiting compliance review"),
    "ERR_DUAL_USE_ESCALATED": (409, "Dual-use goods screening has been escalated and settlement is barred"),
    "ERR_SCREENING_NOT_CLEARED": (409, "Screening has not been cleared for this presentation"),
    "ERR_APPLICANT_KYC_NOT_CLEARED": (422, "Applicant KYC is not cleared"),
    "ERR_ADVISING_BANK_INELIGIBLE": (422, "Advising bank is not eligible"),
    # ---- business temporal ----
    "ERR_SHIPMENT_AFTER_EXPIRY": (422, "Latest shipment date cannot fall after the credit expiry date"),
    "ERR_PRESENTATION_WINDOW_CLOSED": (422, "The presentation period has closed"),
    "ERR_EXAMINATION_PERIOD_EXPIRED": (409, "The examination period has elapsed and the bank is precluded from refusing"),
    "ERR_WAIVER_WINDOW_CLOSED": (409, "The waiver response window has closed"),
    "ERR_CONSENT_WINDOW_CLOSED": (409, "The beneficiary consent window has closed"),
    "ERR_CONFIRMATION_WINDOW_CLOSED": (422, "The confirmation window for this credit is closed"),
    "ERR_CLOCK_REGRESSION": (422, "The logical clock cannot move backwards"),
    # ---- business constraint ----
    "ERR_AMENDMENT_WINDOW_CONFLICT": (409, "Amendment consent window conflicts with another amendment on this credit"),
    "ERR_CONFIRMING_LINE_WINDOW_FULL": (409, "Confirming bank's line is fully occupied over the requested window"),
    "ERR_CONFIRMING_BANK_INELIGIBLE": (422, "Named confirming bank is not eligible to confirm this credit"),
    "ERR_NO_ELIGIBLE_CONFIRMING_BANK": (422, "No eligible confirming bank is available"),
    "ERR_INCOTERM_DOCUMENT_MISMATCH": (422, "Documentary requirements do not match the credit's incoterm"),
    "ERR_PRESENTATION_INCOMPLETE": (422, "Presentation does not answer every mandatory documentary requirement"),
    "ERR_DUPLICATE_KEY": (409, "A record with this key already exists"),
    "ERR_LIVE_REQUEST_EXISTS": (409, "A live request of this kind already exists"),
    "ERR_EMPTY_CHANGE_SET": (422, "Amendment change set is empty or names a field that cannot be amended"),
    # ---- business referential ----
    "ERR_CLAIM_TYPE_MISMATCH": (422, "Claim type is not admitted by the credit's availability"),
    "ERR_BANK_NOT_NOMINATED": (422, "Presenting bank is not nominated under this credit"),
    "ERR_FACILITY_APPLICANT_MISMATCH": (422, "Credit facility does not belong to this applicant or is in another currency"),
    "ERR_FACILITY_EXPIRED": (422, "Credit facility expires before the credit does"),
    "ERR_DISCREPANCY_CODE_UNKNOWN": (422, "Discrepancy code is not recognised for this credit"),
    "ERR_CLAIM_AMOUNT_MISMATCH": (422, "Claimed amount does not match the presented drawing"),
    "ERR_BENEFICIARY_CONSENT_REQUIRED": (422, "Cancelling an issued credit requires the beneficiary's consent"),
    # ---- business fiscal ----
    "ERR_FACILITY_LIMIT_EXCEEDED": (422, "Operation exceeds the applicant's credit facility limit"),
    "ERR_CREDIT_DRAWABLE_EXCEEDED": (422, "Drawing exceeds the amount still available under the credit"),
    "ERR_CHARGES_EXCEED_PROCEEDS": (422, "Charges exceed the drawn amount"),
    "ERR_COLLATERAL_RELEASE_EXCEEDS_POSTED": (422, "Collateral release exceeds the amount posted"),
    "ERR_COLLATERAL_RELEASE_BLOCKED": (422, "Collateral release would strand collateral already credited to open allocations"),
}


class ApiError(Exception):
    """Raised anywhere in a request to abort with a catalogued error."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        status, default_message = ERROR_CATALOG.get(error_id, (422, "Request payload is invalid"))
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else status
        self.message = message if message is not None else default_message


def bail(error_id, message=None):
    raise ApiError(error_id, message)
