"""Error catalog and ApiError exception.

Every error_id and HTTP status below traces verbatim to PRD Section 5
(Error Code Catalogue) and SCAFFOLD 1.6.
"""


class ApiError(Exception):
    """An API error carrying an error_id, message, and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


# error_id -> http_status  (PRD Section 5)
ERROR_STATUS = {
    "ERR_MISSING_USER_CONTEXT": 400,
    "ERR_FORBIDDEN_FOR_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_NOT_ACCOUNT_OWNER": 403,
    "ERR_INVALID_STATE": 409,
    "ERR_ACCOUNT_NOT_ACTIVE": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_INELIGIBLE_GRANTEE": 409,
    "ERR_CHARITY_NOT_VETTED": 409,
    "ERR_BELOW_MINIMUM_GRANT": 422,
    "ERR_VALUATION_INPUT_MISSING": 422,
    "ERR_VALUATION_QUANTITY_INVALID": 422,
    "ERR_POOL_NAV_INVALID": 422,
    "ERR_POOL_CLOSED": 409,
    "ERR_SHARE_BPS_NOT_100": 422,
    "ERR_NAV_PERIOD_OVERLAP": 409,
    "ERR_RECURRING_GRANT_OVERLAP": 409,
    "ERR_NO_CONFIRMED_SUCCESSION": 409,
    "ERR_PENDING_GRANTS_BLOCK_CLOSE": 409,
    "ERR_SUCCESSION_BENEFICIARY_NOT_VETTED": 409,
    "ERR_ACCOUNT_NOT_IN_WIND_DOWN": 409,
    "ERR_INSUFFICIENT_CASH": 409,
    "ERR_INSUFFICIENT_POOL_UNITS": 409,
    "ERR_INSUFFICIENT_GRANTABLE_BALANCE": 409,
    "ERR_DUPLICATE_CHARITY_EIN": 409,
    "ERR_STALE_ACCOUNT_VERSION": 412,
    "ERR_RECEIPT_NOT_FOUND": 404,
}


_DEFAULT_MESSAGES = {
    "ERR_MISSING_USER_CONTEXT": "X-User-ID or X-User-Role header missing or malformed.",
    "ERR_FORBIDDEN_FOR_ROLE": "Caller role not permitted for this endpoint.",
    "ERR_NOT_FOUND": "Referenced resource does not exist.",
    "ERR_INVALID_REQUEST": "Malformed body, invalid enum, missing required field, or amount <= 0.",
    "ERR_NOT_ACCOUNT_OWNER": "Acting DonorAdvisor is not the account's primary_advisor_user_id.",
    "ERR_INVALID_STATE": "Target resource is in a state where the requested transition is not allowed.",
    "ERR_ACCOUNT_NOT_ACTIVE": "Account is not in a state that permits this operation.",
    "ERR_SEGREGATION_OF_DUTIES": "The acting officer recommended this grant and may not act on it.",
    "ERR_INELIGIBLE_GRANTEE": "Charity is a private foundation and cannot be VETTED.",
    "ERR_CHARITY_NOT_VETTED": "Referenced charity is not in status VETTED.",
    "ERR_BELOW_MINIMUM_GRANT": "Grant amount is below the sponsor's minimum grant.",
    "ERR_VALUATION_INPUT_MISSING": "Required pricing inputs for the asset_type are absent on settle.",
    "ERR_VALUATION_QUANTITY_INVALID": "SECURITIES quantity_milli is not divisible by 1000.",
    "ERR_POOL_NAV_INVALID": "nav_per_unit_cents must be greater than zero.",
    "ERR_POOL_CLOSED": "Target pool is CLOSED and cannot receive a new buy allocation.",
    "ERR_SHARE_BPS_NOT_100": "LEGACY_GRANTS beneficiaries' share_bps do not sum to exactly 10000.",
    "ERR_NAV_PERIOD_OVERLAP": "New NavPeriod window overlaps an existing ACTIVE NavPeriod on the same pool.",
    "ERR_RECURRING_GRANT_OVERLAP": "Recurring grant window overlaps an existing SCHEDULED RECURRING grant.",
    "ERR_NO_CONFIRMED_SUCCESSION": "wind-down requires a CONFIRMED LEGACY_GRANTS SuccessionPlan.",
    "ERR_PENDING_GRANTS_BLOCK_CLOSE": "Outstanding grants block the close.",
    "ERR_SUCCESSION_BENEFICIARY_NOT_VETTED": "A LEGACY_GRANTS beneficiary charity is not VETTED.",
    "ERR_ACCOUNT_NOT_IN_WIND_DOWN": "execute-succession requires the account to be in WIND_DOWN.",
    "ERR_INSUFFICIENT_CASH": "Rebalance buy requires more cash than cash_balance_cents holds.",
    "ERR_INSUFFICIENT_POOL_UNITS": "Rebalance redeem exceeds the source allocation's invested value.",
    "ERR_INSUFFICIENT_GRANTABLE_BALANCE": "cash_balance_cents + invested_value_cents is below amount_cents.",
    "ERR_DUPLICATE_CHARITY_EIN": "Charity EIN already in use by a non-REVOKED charity under the sponsor.",
    "ERR_STALE_ACCOUNT_VERSION": "expected_account_version does not match the account's current version.",
    "ERR_RECEIPT_NOT_FOUND": "Requested SubstantiationReceipt id does not exist.",
}


def err(error_id, message=None):
    """Construct an ApiError, looking up the HTTP status from the catalog."""
    return ApiError(error_id, ERROR_STATUS[error_id], message)
