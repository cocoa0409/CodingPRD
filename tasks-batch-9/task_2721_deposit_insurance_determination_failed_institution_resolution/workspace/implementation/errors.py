"""Error catalogue (PRD section 5) and the exception type used to raise them."""


class ApiError(Exception):
    """Raised anywhere in the request pipeline to short-circuit with one error."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or ERROR_MESSAGES.get(error_id, error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_INSTITUTION_NOT_FOUND": 404,
    "ERR_SUBMISSION_NOT_FOUND": 404,
    "ERR_DEPOSITOR_NOT_FOUND": 404,
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_DETERMINATION_NOT_FOUND": 404,
    "ERR_CERTIFICATE_NOT_FOUND": 404,
    "ERR_BIDDER_NOT_FOUND": 404,
    "ERR_BID_NOT_FOUND": 404,
    "ERR_BRANCH_REOPENING_NOT_FOUND": 404,
    "ERR_DISTRIBUTION_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CLOCK_MONOTONICITY": 422,
    "ERR_DEPOSITOR_MISMATCH": 403,
    "ERR_BIDDER_MISMATCH": 403,
    "ERR_STALE_DEPOSITOR_VERSION": 412,
    "ERR_STALE_INSTITUTION_VERSION": 412,
    "ERR_DEPOSITOR_INSTITUTION_MISMATCH": 422,
    "ERR_BID_INSTITUTION_INELIGIBLE": 422,
    "ERR_DUPLICATE_IDENTIFIER": 409,
    "ERR_INSTITUTION_NOT_READY": 409,
    "ERR_INSTITUTION_ALREADY_CLOSED": 409,
    "ERR_SUBMISSION_NOT_PENDING": 409,
    "ERR_DETERMINATION_NOT_PREPARABLE": 409,
    "ERR_DETERMINATION_NOT_PREPARED": 409,
    "ERR_DETERMINATION_NOT_UNDER_REVIEW": 409,
    "ERR_INSTITUTION_NOT_CLOSED": 409,
    "ERR_ACTIVE_DETERMINATION_EXISTS": 409,
    "ERR_CERTIFICATE_ALREADY_PAID": 409,
    "ERR_HOLD_NOT_PLACED": 409,
    "ERR_NOTICE_NOT_ACKNOWLEDGED": 409,
    "ERR_NOTICE_NOT_SENT": 409,
    "ERR_MARKETING_ACTION_INVALID": 409,
    "ERR_MARKETING_NOT_OPEN": 409,
    "ERR_BID_NOT_WITHDRAWABLE": 409,
    "ERR_LEAST_COST_TEST_NOT_OPEN": 409,
    "ERR_LEAST_COST_TEST_NOT_EVALUATED": 409,
    "ERR_BRANCH_NOT_READY": 409,
    "ERR_OUTSIDE_REOPEN_WINDOW": 422,
    "ERR_BRANCH_NOT_RESCHEDULABLE": 409,
    "ERR_SEGREGATION_OF_DUTIES_VIOLATION": 403,
    "ERR_PROVISIONAL_VARIANT_NOT_CERTIFIABLE": 422,
    "ERR_OWNERSHIP_SHARES_UNBALANCED": 422,
    "ERR_BRANCH_WINDOW_OVERLAP": 409,
    "ERR_BID_WINDOW_CLOSED": 422,
    "ERR_DATA_ROOM_WINDOW_CONFLICT": 409,
    "ERR_BIDDER_NOT_QUALIFIED": 422,
    "ERR_BIDDER_INELIGIBLE": 422,
    "ERR_DISTRIBUTION_NOT_DECLARED": 409,
    "ERR_DISTRIBUTION_NOT_SETTLED": 409,
    "ERR_PRIORITY_CLASS_OUT_OF_ORDER": 409,
    "ERR_NOT_LATEST_DIVIDEND_ROUND": 409,
    "ERR_RECEIVERSHIP_NOT_TERMINABLE": 409,
    "ERR_INSUFFICIENT_RECEIVERSHIP_CASH": 402,
    "ERR_DISPOSITION_EXPENSE_EXCEEDS_PROCEEDS": 422,
}

ERROR_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers missing or role unknown",
    "ERR_UNAUTHORIZED": "Role not permitted for this operation",
    "ERR_INSTITUTION_NOT_FOUND": "Institution not found",
    "ERR_SUBMISSION_NOT_FOUND": "Readiness submission not found",
    "ERR_DEPOSITOR_NOT_FOUND": "Depositor record not found",
    "ERR_ACCOUNT_NOT_FOUND": "Deposit account not found",
    "ERR_DETERMINATION_NOT_FOUND": "Insurance determination not found",
    "ERR_CERTIFICATE_NOT_FOUND": "Receivership certificate not found",
    "ERR_BIDDER_NOT_FOUND": "Bidder not found",
    "ERR_BID_NOT_FOUND": "Bid not found",
    "ERR_BRANCH_REOPENING_NOT_FOUND": "Branch reopening not found",
    "ERR_DISTRIBUTION_NOT_FOUND": "Dividend distribution not found",
    "ERR_INVALID_REQUEST": "Request body failed shape, type, enum or range validation",
    "ERR_CLOCK_MONOTONICITY": "Logical clock cannot move backwards",
    "ERR_DEPOSITOR_MISMATCH": "Depositor may only act on their own record",
    "ERR_BIDDER_MISMATCH": "Bidder may only act on their own bids",
    "ERR_STALE_DEPOSITOR_VERSION": (
        "expected_depositor_record_version does not match the current depositor "
        "record version"
    ),
    "ERR_STALE_INSTITUTION_VERSION": (
        "expected_institution_version does not match the current institution version"
    ),
    "ERR_DEPOSITOR_INSTITUTION_MISMATCH": (
        "Depositor belongs to a different institution than the deposit account"
    ),
    "ERR_BID_INSTITUTION_INELIGIBLE": "Institution is not in a biddable state",
    "ERR_DUPLICATE_IDENTIFIER": "Identifier already in use",
    "ERR_INSTITUTION_NOT_READY": "Institution is not resolution-ready",
    "ERR_INSTITUTION_ALREADY_CLOSED": "Institution is already in receivership",
    "ERR_SUBMISSION_NOT_PENDING": "Readiness submission is no longer pending",
    "ERR_DETERMINATION_NOT_PREPARABLE": "Determination is not in a preparable state",
    "ERR_DETERMINATION_NOT_PREPARED": "Determination has not been prepared",
    "ERR_DETERMINATION_NOT_UNDER_REVIEW": "Determination is not under review",
    "ERR_INSTITUTION_NOT_CLOSED": "Institution has not been closed into receivership",
    "ERR_ACTIVE_DETERMINATION_EXISTS": (
        "An active determination already exists for this depositor"
    ),
    "ERR_CERTIFICATE_ALREADY_PAID": (
        "Certificate has already received dividends and cannot be superseded"
    ),
    "ERR_HOLD_NOT_PLACED": "No active hold on this account",
    "ERR_NOTICE_NOT_ACKNOWLEDGED": (
        "Depositor has not acknowledged the determination notice"
    ),
    "ERR_NOTICE_NOT_SENT": "No notice pending acknowledgement",
    "ERR_MARKETING_ACTION_INVALID": (
        "Franchise marketing action not allowed in the current state"
    ),
    "ERR_MARKETING_NOT_OPEN": "Franchise marketing window is not open",
    "ERR_BID_NOT_WITHDRAWABLE": "Bid can no longer be withdrawn",
    "ERR_LEAST_COST_TEST_NOT_OPEN": (
        "Least-cost test cannot be evaluated in the current state"
    ),
    "ERR_LEAST_COST_TEST_NOT_EVALUATED": "Least-cost test has not been evaluated",
    "ERR_BRANCH_NOT_READY": "Branch is not staffed and ready",
    "ERR_OUTSIDE_REOPEN_WINDOW": (
        "Logical clock is outside the half-open reopening window"
    ),
    "ERR_BRANCH_NOT_RESCHEDULABLE": "Branch reopening can no longer be rescheduled",
    "ERR_SEGREGATION_OF_DUTIES_VIOLATION": (
        "Preparer may not certify their own determination"
    ),
    "ERR_PROVISIONAL_VARIANT_NOT_CERTIFIABLE": (
        "Provisional per-account variant cannot be certified"
    ),
    "ERR_OWNERSHIP_SHARES_UNBALANCED": (
        "Joint account co-owner shares do not sum to 10000 bps"
    ),
    "ERR_BRANCH_WINDOW_OVERLAP": (
        "Branch reopening window overlaps an existing window for this branch"
    ),
    "ERR_BID_WINDOW_CLOSED": "Bid deadline has passed",
    "ERR_DATA_ROOM_WINDOW_CONFLICT": (
        "Data-room reservation violates the 60-minute separation buffer"
    ),
    "ERR_BIDDER_NOT_QUALIFIED": "Bidder is not qualified",
    "ERR_BIDDER_INELIGIBLE": "Bidder fails the capital or CAMELS eligibility floors",
    "ERR_DISTRIBUTION_NOT_DECLARED": "Dividend round is not in DECLARED state",
    "ERR_DISTRIBUTION_NOT_SETTLED": "Dividend round is not settled",
    "ERR_PRIORITY_CLASS_OUT_OF_ORDER": "Priority classes must be paid in order",
    "ERR_NOT_LATEST_DIVIDEND_ROUND": (
        "Only the latest settled dividend round may be voided"
    ),
    "ERR_RECEIVERSHIP_NOT_TERMINABLE": (
        "Receivership still has open holds or dividend rounds"
    ),
    "ERR_INSUFFICIENT_RECEIVERSHIP_CASH": (
        "Receivership cash is insufficient for the declared dividend"
    ),
    "ERR_DISPOSITION_EXPENSE_EXCEEDS_PROCEEDS": (
        "Disposition expense exceeds gross proceeds"
    ),
}
