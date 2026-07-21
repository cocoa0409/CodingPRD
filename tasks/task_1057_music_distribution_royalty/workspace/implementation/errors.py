"""Error catalogue (PRD §5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or ERROR_MESSAGES.get(error_id, error_id)
        self.http_status = http_status if http_status is not None else ERROR_STATUS[error_id]


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FORBIDDEN_OWNERSHIP": 403,
    "ERR_VALIDATION": 400,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_METADATA_NONCOMPLIANT": 422,
    "ERR_ISRC_MISSING": 422,
    "ERR_SPLIT_SHEET_NOT_LOCKED": 409,
    "ERR_SPLIT_SHEET_EMPTY": 422,
    "ERR_SPLIT_TOTAL_INVALID": 422,
    "ERR_SPLIT_NOT_ACCEPTED": 409,
    "ERR_DUPLICATE_IDENTIFIER": 409,
    "ERR_RELEASE_DATE_TOO_SOON": 422,
    "ERR_DELIVERY_LEAD_TIME_VIOLATION": 422,
    "ERR_STORE_WINDOW_SATURATED": 409,
    "ERR_STATEMENT_PERIOD_OVERLAP": 409,
    "ERR_LINE_OUTSIDE_PERIOD": 422,
    "ERR_PRE_SAVE_WINDOW_CLOSED": 422,
    "ERR_REVERSAL_WINDOW_EXPIRED": 422,
    "ERR_SUBSCRIPTION_INACTIVE": 402,
    "ERR_RELEASE_SLOTS_EXHAUSTED": 402,
    "ERR_CONTENT_ID_NOT_ENTITLED": 403,
    "ERR_TAX_FORM_NOT_VERIFIED": 422,
    "ERR_PAYOUT_BELOW_THRESHOLD": 422,
    "ERR_1099_THRESHOLD_NOT_MET": 422,
    "ERR_RELEASE_DATE_NOT_REACHED": 422,
}

ERROR_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers missing or role not recognised.",
    "ERR_UNAUTHORIZED": "The acting role is not authorised for this endpoint.",
    "ERR_FORBIDDEN_OWNERSHIP": "The acting principal does not own the addressed resource.",
    "ERR_VALIDATION": "The request body or query parameters failed validation.",
    "ERR_RESOURCE_NOT_FOUND": "The requested resource does not exist.",
    "ERR_INVALID_STATE": "The resource is not in a state permitting this transition.",
    "ERR_STALE_VERSION": "The supplied expected version does not match the current version.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this operator performing this step.",
    "ERR_METADATA_NONCOMPLIANT": "The store requires an explicit-content declaration on every track.",
    "ERR_ISRC_MISSING": "The store requires an ISRC on every track.",
    "ERR_SPLIT_SHEET_NOT_LOCKED": "Every track of the release must hold a locked split sheet.",
    "ERR_SPLIT_SHEET_EMPTY": "The split sheet holds no shares.",
    "ERR_SPLIT_TOTAL_INVALID": "The split sheet's shares do not total 10000 basis points.",
    "ERR_SPLIT_NOT_ACCEPTED": "At least one share of the sheet has not been accepted.",
    "ERR_DUPLICATE_IDENTIFIER": "A uniqueness constraint was violated.",
    "ERR_RELEASE_DATE_TOO_SOON": "The release date does not respect the minimum lead time.",
    "ERR_DELIVERY_LEAD_TIME_VIOLATION": "The scheduled send does not respect the store's lead time.",
    "ERR_STORE_WINDOW_SATURATED": "The store has no free delivery window at that instant.",
    "ERR_STATEMENT_PERIOD_OVERLAP": "The reporting period overlaps an existing statement.",
    "ERR_LINE_OUTSIDE_PERIOD": "A reported line falls outside the statement period.",
    "ERR_PRE_SAVE_WINDOW_CLOSED": "The pre-save window is not open.",
    "ERR_REVERSAL_WINDOW_EXPIRED": "The payout reversal window has expired.",
    "ERR_SUBSCRIPTION_INACTIVE": "The artist has no active subscription.",
    "ERR_RELEASE_SLOTS_EXHAUSTED": "No release slots remain on the plan.",
    "ERR_CONTENT_ID_NOT_ENTITLED": "The plan does not permit Content-ID monetisation.",
    "ERR_TAX_FORM_NOT_VERIFIED": "The payee's tax form is not verified.",
    "ERR_PAYOUT_BELOW_THRESHOLD": "The payout is below the payment threshold.",
    "ERR_1099_THRESHOLD_NOT_MET": "The reportable total is below the 1099 threshold.",
    "ERR_RELEASE_DATE_NOT_REACHED": "The release date has not been reached.",
}
