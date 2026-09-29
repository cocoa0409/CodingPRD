"""Error class and the complete error catalogue (PRD §5 / SCAFFOLD §1.6)."""

ERROR_STATUS = {
    # -- schema / request shape --------------------------------------------
    "ERR_VALIDATION": 422,
    "ERR_LICENSE_MODE_FIELDS_INVALID": 422,
    "ERR_CLOCK_REWIND": 422,
    "ERR_TIER_CODE_DUPLICATE": 409,
    "ERR_LEDGER_SOURCE_NOT_MANUAL": 422,
    # -- not found ---------------------------------------------------------
    "ERR_COMPOSER_NOT_FOUND": 404,
    "ERR_COMPOSER_AGREEMENT_NOT_FOUND": 404,
    "ERR_COMPOSITION_NOT_FOUND": 404,
    "ERR_SEARCH_PROFILE_NOT_FOUND": 404,
    "ERR_LICENSE_TIER_NOT_FOUND": 404,
    "ERR_LICENSEE_NOT_FOUND": 404,
    "ERR_SYNC_REQUEST_NOT_FOUND": 404,
    "ERR_LICENSE_NOT_FOUND": 404,
    "ERR_BLANKET_AGREEMENT_NOT_FOUND": 404,
    "ERR_USAGE_REPORT_NOT_FOUND": 404,
    "ERR_CUE_SHEET_NOT_FOUND": 404,
    "ERR_FINGERPRINT_MATCH_NOT_FOUND": 404,
    "ERR_INFRINGEMENT_CLAIM_NOT_FOUND": 404,
    "ERR_ROYALTY_STATEMENT_NOT_FOUND": 404,
    "ERR_ROYALTY_LEDGER_ENTRY_NOT_FOUND": 404,
    # -- authorization -----------------------------------------------------
    "ERR_UNAUTHORIZED": 403,
    "ERR_LICENSEE_MISMATCH": 403,
    "ERR_COMPOSER_IDENTITY_MISMATCH": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # -- concurrency -------------------------------------------------------
    "ERR_COMPOSITION_VERSION_CONFLICT": 412,
    "ERR_COMPOSER_VERSION_CONFLICT": 412,
    # -- state -------------------------------------------------------------
    "ERR_AGREEMENT_STATE_INVALID": 409,
    "ERR_COMPOSITION_STATE_INVALID": 409,
    "ERR_SYNC_REQUEST_STATE_INVALID": 409,
    "ERR_LICENSE_STATE_INVALID": 409,
    "ERR_BLANKET_STATE_INVALID": 409,
    "ERR_REPORT_STATE_INVALID": 409,
    "ERR_CUE_SHEET_STATE_INVALID": 409,
    "ERR_CLAIM_STATE_INVALID": 409,
    "ERR_STATEMENT_STATE_INVALID": 409,
    # -- business rules ----------------------------------------------------
    "ERR_SHARE_SPLIT_NOT_100": 422,
    "ERR_WORK_FOR_HIRE_TERMS_INVALID": 422,
    "ERR_AGREEMENT_NOT_ACTIVE": 409,
    "ERR_COMPOSITION_NOT_LICENSABLE": 409,
    "ERR_ACTIVE_CLAIM_BLOCKS_LICENSE": 409,
    "ERR_QUOTE_EXPIRED": 409,
    "ERR_EXCLUSIVE_WINDOW_CONFLICT": 409,
    "ERR_TERM_OUTSIDE_COVERAGE": 422,
    "ERR_BLANKET_NOT_ACTIVE": 409,
    "ERR_BLANKET_COVERAGE_OVERLAP": 409,
    "ERR_COVERAGE_DATES_INVALID": 422,
    "ERR_COVERAGE_WINDOW_PASSED": 409,
    "ERR_REPORT_PERIOD_INVALID": 422,
    "ERR_REPORT_PERIOD_DUPLICATE": 409,
    "ERR_REPORT_HAS_NO_CUE_SHEETS": 409,
    "ERR_CUE_SHEET_PARENT_INVALID": 422,
    "ERR_CUE_COMPOSITION_NOT_COVERED": 409,
    "ERR_CUE_SHEET_HAS_NO_CREDITS": 409,
    "ERR_COMPOSER_NOT_AFFILIATED": 409,
    "ERR_TIER_INCOMPATIBLE": 422,
    "ERR_SCALE_NOT_ALLOWED_FOR_TIER": 422,
    "ERR_TERM_OUTSIDE_TIER_RANGE": 422,
    "ERR_CREDIT_LIMIT_EXCEEDED": 409,
    "ERR_REVISION_LIMIT_REACHED": 409,
    "ERR_AMENDMENT_LIMIT_REACHED": 409,
    "ERR_NO_EDIT_WORK_REQUESTED": 409,
    "ERR_EDIT_PASS_REQUIRED": 409,
    "ERR_LICENSE_NOT_ISSUED": 409,
    "ERR_DELIVERABLE_COUNT_SHORT": 422,
    "ERR_METADATA_INCOMPLETE": 409,
    "ERR_COMPOSITION_HAS_ACTIVE_LICENSES": 409,
    "ERR_TERM_NOT_STARTED": 409,
    "ERR_PAYMENT_EXCEEDS_FEE": 422,
    "ERR_CONFIDENCE_BELOW_CLAIM_THRESHOLD": 422,
    "ERR_CONFIDENCE_BELOW_NOTICE_THRESHOLD": 409,
    "ERR_MATCH_ALREADY_CLAIMED": 409,
    "ERR_SETTLEMENT_BELOW_FLOOR": 422,
    "ERR_STATEMENT_PERIOD_OVERLAP": 409,
    "ERR_STATEMENT_NO_ACTIVITY": 409,
    "ERR_STATEMENT_NOT_PAYABLE": 409,
    "ERR_WEIGHTS_NOT_100": 422,
}


class ApiError(Exception):
    """Raised anywhere in a handler; converted to the error envelope in app.py."""

    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 422)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    text = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return "Request refused: %s." % text


def fail(error_id, message=None):
    raise ApiError(error_id, message)
