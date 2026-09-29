"""Error catalogue — PRD §5 / §2.9.

Every identifier and HTTP status below is copied verbatim from the PRD's
error-code catalogue.  Nothing else in the codebase invents an error id.
"""

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_STALE_OFFERING_VERSION": 412,
    "ERR_STALE_SHARE_CLASS_VERSION": 412,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_OFFERING_NOT_EFFECTIVE": 409,
    "ERR_SHARE_CLASS_CLOSED": 409,
    "ERR_SELLING_AGREEMENT_NOT_ACTIVE": 409,
    "ERR_BROKER_DEALER_BARRED": 409,
    "ERR_REPURCHASE_PLAN_SUSPENDED": 409,
    "ERR_NO_PUBLISHED_NAV": 409,
    "ERR_VOTE_NOT_OPEN": 409,
    "ERR_REPURCHASE_PERIOD_CLOSED": 409,
    "ERR_REPURCHASE_PERIOD_WINDOW_CONFLICT": 409,
    "ERR_PERIOD_NOT_READY_FOR_PROCESSING": 409,
    "ERR_NAV_PERIOD_OVERLAP": 409,
    "ERR_NAV_PERIOD_NOT_ELAPSED": 409,
    "ERR_ESCROW_DEADLINE_PASSED": 409,
    "ERR_RESCISSION_WINDOW_EXPIRED": 409,
    "ERR_PAYMENT_DATE_NOT_REACHED": 409,
    "ERR_EFFECTIVE_DATE_NOT_REACHED": 409,
    "ERR_LOT_PARTIALLY_REPURCHASED": 409,
    "ERR_DECLARATION_ALREADY_PAID": 409,
    "ERR_SUITABILITY_NOT_DOCUMENTED": 422,
    "ERR_CONCENTRATION_LIMIT_EXCEEDED": 422,
    "ERR_BELOW_MINIMUM_INVESTMENT": 422,
    "ERR_UNCOVERED_DISTRIBUTION_UNACKNOWLEDGED": 422,
    "ERR_ADVISOR_OPINION_REQUIRED": 422,
    "ERR_INSUFFICIENT_SHARES": 422,
    "ERR_DUPLICATE_STOCKHOLDER_VOTE": 422,
    "ERR_DUPLICATE_SHARE_CLASS_CODE": 422,
    "ERR_DUPLICATE_REPURCHASE_PERIOD": 422,
    "ERR_DUPLICATE_INVESTOR_EMAIL": 422,
    "ERR_DUPLICATE_CRD_NUMBER": 422,
    "ERR_COMMISSION_CAP_EXCEEDED": 422,
    "ERR_OFFERING_MAXIMUM_EXCEEDED": 422,
    "ERR_MINIMUM_OFFERING_NOT_MET": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing, blank or name an unknown role.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not permitted to perform this operation.",
    "ERR_NOT_RESOURCE_OWNER": "The acting caller does not own the targeted resource.",
    "ERR_INVALID_REQUEST": "The request payload is malformed or fails a declared constraint.",
    "ERR_RESOURCE_NOT_FOUND": "A referenced resource does not exist.",
    "ERR_STALE_OFFERING_VERSION": "expected_offering_version does not match the stored offering version.",
    "ERR_STALE_SHARE_CLASS_VERSION": "expected_share_class_version does not match the stored share class version.",
    "ERR_INVALID_STATE_TRANSITION": "The requested transition is not defined for the current state.",
    "ERR_OFFERING_NOT_EFFECTIVE": "The offering's registration status is not EFFECTIVE.",
    "ERR_SHARE_CLASS_CLOSED": "The share class is closed to new subscriptions.",
    "ERR_SELLING_AGREEMENT_NOT_ACTIVE": "The selling agreement is not ACTIVE.",
    "ERR_BROKER_DEALER_BARRED": "The broker-dealer is BARRED.",
    "ERR_REPURCHASE_PLAN_SUSPENDED": "The offering's share repurchase plan is not ACTIVE.",
    "ERR_NO_PUBLISHED_NAV": "No PUBLISHED valuation record exists for the share class.",
    "ERR_VOTE_NOT_OPEN": "The liquidity event is not open for voting.",
    "ERR_REPURCHASE_PERIOD_CLOSED": "The repurchase period's request window is not open.",
    "ERR_REPURCHASE_PERIOD_WINDOW_CONFLICT": "The request window conflicts with a sibling period.",
    "ERR_PERIOD_NOT_READY_FOR_PROCESSING": "The repurchase period has not reached its request cutoff.",
    "ERR_NAV_PERIOD_OVERLAP": "The valuation period overlaps a sibling record of the same class.",
    "ERR_NAV_PERIOD_NOT_ELAPSED": "The valuation period has not fully elapsed.",
    "ERR_ESCROW_DEADLINE_PASSED": "The escrow deadline date has passed.",
    "ERR_RESCISSION_WINDOW_EXPIRED": "The rescission window has expired.",
    "ERR_PAYMENT_DATE_NOT_REACHED": "The declaration's payment date has not been reached.",
    "ERR_EFFECTIVE_DATE_NOT_REACHED": "The proposed effective date has not been reached.",
    "ERR_LOT_PARTIALLY_REPURCHASED": "The minted share lot has already been partially repurchased.",
    "ERR_DECLARATION_ALREADY_PAID": "A declaration for this record date has already been paid.",
    "ERR_SUITABILITY_NOT_DOCUMENTED": "The investor's suitability documentation is not on file.",
    "ERR_CONCENTRATION_LIMIT_EXCEEDED": "The subscription would breach the investor's concentration limit.",
    "ERR_BELOW_MINIMUM_INVESTMENT": "The tendered amount is below the applicable minimum investment.",
    "ERR_UNCOVERED_DISTRIBUTION_UNACKNOWLEDGED": "The uncovered distribution lacks board acknowledgement.",
    "ERR_ADVISOR_OPINION_REQUIRED": "An independent valuation advisor opinion reference is required.",
    "ERR_INSUFFICIENT_SHARES": "The requested share units are not available.",
    "ERR_DUPLICATE_STOCKHOLDER_VOTE": "A ballot has already been cast for this liquidity event.",
    "ERR_DUPLICATE_SHARE_CLASS_CODE": "The offering already has a share class with this class code.",
    "ERR_DUPLICATE_REPURCHASE_PERIOD": "The offering already has a period for this month.",
    "ERR_DUPLICATE_INVESTOR_EMAIL": "Another investor already uses this email.",
    "ERR_DUPLICATE_CRD_NUMBER": "Another broker-dealer already uses this CRD number.",
    "ERR_COMMISSION_CAP_EXCEEDED": "The class's upfront load exceeds the agreement's commission ceiling.",
    "ERR_OFFERING_MAXIMUM_EXCEEDED": "The registered maximum offering amount would be exceeded.",
    "ERR_MINIMUM_OFFERING_NOT_MET": "The minimum offering amount has not been met.",
}


class ApiError(Exception):
    """Raised anywhere in the request path; rendered by the Flask error handler."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS[error_id]
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
