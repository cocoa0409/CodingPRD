"""Error catalog — exact error IDs and HTTP statuses from SCAFFOLD §1.6 / PRD §5."""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


HTTP_STATUS = {
    # auth
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    # not found
    "ERR_SYNDICATION_NOT_FOUND": 404,
    "ERR_OFFERING_NOT_FOUND": 404,
    "ERR_SUBSCRIPTION_NOT_FOUND": 404,
    "ERR_INVESTOR_NOT_FOUND": 404,
    "ERR_PROPERTY_NOT_FOUND": 404,
    "ERR_DOCUMENT_NOT_FOUND": 404,
    "ERR_CAPITAL_CALL_NOT_FOUND": 404,
    "ERR_CONTRIBUTION_NOT_FOUND": 404,
    "ERR_QUARTERLY_REPORT_NOT_FOUND": 404,
    "ERR_DISTRIBUTION_NOT_FOUND": 404,
    "ERR_CAPITAL_EVENT_NOT_FOUND": 404,
    "ERR_K1_PACKAGE_NOT_FOUND": 404,
    "ERR_TRANSFER_REQUEST_NOT_FOUND": 404,
    # state
    "ERR_INVALID_STATE": 409,
    "ERR_SYNDICATION_NOT_ACTIVE": 409,
    "ERR_OFFERING_NOT_OPEN": 409,
    "ERR_OFFERING_NOT_ACCEPTING_CALLS": 409,
    "ERR_PROPERTY_NOT_TRANSACTABLE": 409,
    "ERR_PROPERTY_NOT_OWNED": 409,
    "ERR_SUBSCRIPTION_NOT_FUNDED": 409,
    # business safety / compliance
    "ERR_SELF_VERIFICATION_FORBIDDEN": 403,
    "ERR_SELF_APPROVAL_FORBIDDEN": 403,
    "ERR_INVESTOR_CLASS_INSUFFICIENT": 422,
    "ERR_ACCREDITATION_DOC_MISSING": 422,
    # business constraint
    "ERR_MISSING_REQUIRED_DOCUMENTS": 422,
    "ERR_BELOW_MIN_SUBSCRIPTION": 422,
    "ERR_NON_ACCREDITED_CAP_REACHED": 422,
    "ERR_DUPLICATE_QUARTERLY_REPORT": 409,
    "ERR_TRANSFER_EXCEEDS_FUNDED": 422,
    "ERR_BUYER_NOT_ONBOARDED": 422,
    "ERR_SELF_TRANSFER": 422,
    "ERR_REPORT_LOCKED_BY_DISTRIBUTION": 409,
    "ERR_PROPERTY_HAS_ACTIVE_CAPITAL_EVENT": 409,
    "ERR_REPORT_NOT_PUBLISHED": 422,
    "ERR_CAPITAL_EVENT_NOT_EXECUTED": 422,
    # fiscal
    "ERR_ESCROW_OVERPAYMENT": 422,
    "ERR_ESCROW_PAST_DUE": 422,
    "ERR_ESCROW_INCOMPLETE": 422,
    "ERR_ESCROW_ALREADY_RELEASED": 409,
    "ERR_INSUFFICIENT_PROCEEDS": 422,
    "ERR_NO_FUNDED_SUBSCRIPTIONS": 422,
    "ERR_EMPTY_DISTRIBUTION_POOL": 422,
    "ERR_OFFERING_HAS_OPEN_SUBSCRIPTIONS": 409,
    "ERR_OFFERING_HAS_OPEN_CAPITAL_CALLS": 409,
    "ERR_OFFERING_UNRETURNED_CAPITAL": 409,
    "ERR_DISTRIBUTION_NOT_PAID": 409,
    "ERR_NO_K1_BASE": 422,
    # temporal
    "ERR_FUTURE_REPORT_PERIOD": 422,
    # concurrency
    "ERR_STALE_SUBSCRIPTION_VERSION": 412,
    "ERR_STALE_DISTRIBUTION_VERSION": 412,
    # portal
    "ERR_PORTAL_ACCESS_DENIED": 403,
    "ERR_NOT_YOUR_CONTRIBUTION": 403,
    # generic
    "ERR_INVALID_REQUEST": 400,
    # Referenced by the scaffold state machine but omitted from the §1.6 table;
    # 409 matches the other offering/syndication state guards.
    "ERR_OFFERING_NOT_PUBLISHABLE": 409,
    "ERR_SYNDICATION_HAS_OPEN_OFFERINGS": 409,
    # Optional-OCC companions for the syndication/offering lifecycle actions
    # (PRD 2.7: "the same stale-version comparison applies" — HTTP 412).
    "ERR_STALE_SYNDICATION_VERSION": 412,
    "ERR_STALE_OFFERING_VERSION": 412,
    # Fallback for resources without a catalogued not-found id
    # (InvestorPortalSession, DistributionLine) and unmatched routes.
    "ERR_NOT_FOUND": 404,
}


def raise_error(error_id: str, message: str = ""):
    raise ApiError(error_id, HTTP_STATUS[error_id], message or error_id)
