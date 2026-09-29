"""Error catalogue (PRD section 5) and the ApiError exception."""


ERROR_CATALOG = {
    # auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # schema
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_OWNER_NOT_FOUND": 404,
    "ERR_MERCHANT_NOT_FOUND": 404,
    "ERR_RESERVE_ACCOUNT_NOT_FOUND": 404,
    "ERR_BATCH_NOT_FOUND": 404,
    "ERR_ALERT_NOT_FOUND": 404,
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_TERMINATION_DECISION_NOT_FOUND": 404,
    "ERR_APPEAL_NOT_FOUND": 404,
    "ERR_FORECAST_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_APPLICATION_VERSION": 412,
    "ERR_STALE_RESERVE_ACCOUNT_VERSION": 412,
    # state
    "ERR_APPLICATION_STATE_INVALID": 409,
    "ERR_MERCHANT_ACCOUNT_STATE_INVALID": 409,
    "ERR_FUNDING_STATE_INVALID": 409,
    "ERR_RESERVE_ACCOUNT_CLOSED": 409,
    "ERR_BATCH_STATE_INVALID": 409,
    "ERR_ALERT_STATE_INVALID": 409,
    "ERR_PROGRAM_STATE_INVALID": 409,
    "ERR_TERMINATION_STATE_INVALID": 409,
    "ERR_APPEAL_STATE_INVALID": 409,
    # underwriting safety
    "ERR_PROHIBITED_BUSINESS_CATEGORY": 422,
    "ERR_SANCTIONED_BENEFICIAL_OWNER": 422,
    "ERR_OWNER_SCREENING_INCOMPLETE": 409,
    "ERR_OWNERSHIP_COVERAGE_INSUFFICIENT": 422,
    "ERR_VERIFICATION_NOT_PASSED": 409,
    # referential
    "ERR_CREDIT_ASSESSMENT_REQUIRED": 409,
    "ERR_BENEFICIAL_OWNERS_REQUIRED": 409,
    "ERR_SUPERSEDED_APPLICATION_INVALID": 409,
    "ERR_APPEAL_DECISION_NOT_EXECUTED": 409,
    "ERR_REMEDIATION_NOT_REQUIRED": 409,
    # temporal
    "ERR_ACTIVITY_DATE_IN_FUTURE": 422,
    "ERR_MONITORING_RUN_DATE_REGRESSION": 409,
    "ERR_REMEDIATION_WINDOW_OVERLAP": 409,
    "ERR_RELEASE_TRANCHE_COOLING_VIOLATION": 409,
    "ERR_APPEAL_WINDOW_EXPIRED": 409,
    "ERR_SETTLEMENT_PERIOD_INVALID": 422,
    "ERR_SETTLEMENT_PERIOD_OVERLAP": 409,
    "ERR_PAYOUT_NOT_DUE": 409,
    # uniqueness / sequence / content
    "ERR_DUPLICATE_ACTIVITY_DATE": 409,
    "ERR_DUPLICATE_CATEGORY_RULE": 409,
    "ERR_DUPLICATE_APPEAL": 409,
    "ERR_MONTH_INDEX_OUT_OF_SEQUENCE": 409,
    "ERR_EMPTY_SETTLEMENT_PERIOD": 409,
    "ERR_GROSS_VOLUME_MISMATCH": 422,
    # fiscal
    "ERR_MONTHLY_VOLUME_LIMIT_EXCEEDED": 422,
    "ERR_NO_RELEASABLE_BALANCE": 409,
    "ERR_RELEASE_AMOUNT_EXCEEDS_RELEASABLE": 422,
}


DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and the role must be recognised.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not permitted to perform this operation.",
    "ERR_NOT_RESOURCE_OWNER": "The acting principal does not own the target resource.",
    "ERR_SEGREGATION_OF_DUTIES": "The acting user already took a conflicting step on this object.",
    "ERR_INVALID_REQUEST": "The request payload or query string is invalid.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_CATALOG.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )


def fail(error_id, message=None):
    raise ApiError(error_id, message)
