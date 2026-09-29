"""Error catalogue (PRD section 5) and the ApiError exception."""

ERROR_HTTP = {
    # --- auth / authz ---
    "ERR_MISSING_USER_HEADER": 401,
    "ERR_UNKNOWN_ACTOR": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_STORE_SCOPE_VIOLATION": 403,
    "ERR_SELF_APPROVAL_FORBIDDEN": 403,
    # --- request shape ---
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_DATE_RANGE": 400,
    # --- existence ---
    "ERR_JURISDICTION_NOT_FOUND": 404,
    "ERR_ENGAGEMENT_NOT_FOUND": 404,
    "ERR_STORE_NOT_FOUND": 404,
    "ERR_INVENTORY_LOT_NOT_FOUND": 404,
    "ERR_CONSIGNMENT_NOT_FOUND": 404,
    "ERR_MARKDOWN_STAGE_NOT_FOUND": 404,
    "ERR_LICENSE_NOT_FOUND": 404,
    "ERR_EMPLOYEE_NOT_FOUND": 404,
    "ERR_SALES_DAY_NOT_FOUND": 404,
    "ERR_EXPENSE_ITEM_NOT_FOUND": 404,
    "ERR_LEASE_DISPOSITION_NOT_FOUND": 404,
    "ERR_SETTLEMENT_NOT_FOUND": 404,
    # --- uniqueness ---
    "ERR_DUPLICATE_JURISDICTION_CODE": 409,
    "ERR_DUPLICATE_STORE_CODE": 409,
    "ERR_DUPLICATE_EMPLOYEE_CODE": 409,
    "ERR_DUPLICATE_SALES_DAY": 409,
    "ERR_DUPLICATE_CLAIM_CODE": 400,
    # --- optimistic concurrency ---
    "ERR_STALE_ENGAGEMENT_VERSION": 412,
    "ERR_STALE_STORE_VERSION": 412,
    # --- state ---
    "ERR_ENGAGEMENT_STATE_INVALID": 409,
    "ERR_STORE_NOT_SELLING": 409,
    "ERR_STORE_STATE_INVALID": 409,
    "ERR_LICENSE_STATE_INVALID": 409,
    "ERR_STAGE_STATE_INVALID": 409,
    "ERR_CONSIGNMENT_STATE_INVALID": 409,
    "ERR_EMPLOYEE_STATE_INVALID": 409,
    "ERR_SALES_DAY_STATE_INVALID": 409,
    "ERR_EXPENSE_STATE_INVALID": 409,
    "ERR_LEASE_STATE_INVALID": 409,
    "ERR_SETTLEMENT_STATE_INVALID": 409,
    # --- compliance posture ---
    "ERR_ENGAGEMENT_COMPLIANCE_FROZEN": 409,
    "ERR_ENGAGEMENT_COMPLIANCE_RESTRICTED": 409,
    # --- licensing / advertising ---
    "ERR_LICENSE_NOT_ACTIVE": 409,
    "ERR_LICENSE_COOLING_OFF": 409,
    "ERR_LICENSE_PERIOD_TOO_LONG": 400,
    "ERR_PROHIBITED_ADVERTISING_CLAIM": 409,
    "ERR_ADVERTISING_DISCLOSURE_REQUIRED": 409,
    # --- augmentation ---
    "ERR_AUGMENTATION_PROHIBITED": 409,
    "ERR_AUGMENTATION_DISCLOSURE_MISSING": 409,
    "ERR_AUGMENTATION_CAP_EXCEEDED": 422,
    "ERR_AUGMENTATION_SOURCE_FORBIDDEN": 400,
    "ERR_DELIVERY_SLOT_CAPACITY": 409,
    "ERR_RETURN_UNITS_EXCEED_UNSOLD": 422,
    # --- markdown cadence ---
    "ERR_STAGE_WINDOW_OVERLAP": 409,
    "ERR_STAGE_SEQUENCE_INVALID": 422,
    "ERR_STAGE_ALREADY_ACTIVE": 409,
    # --- sales ---
    "ERR_SALES_DAY_OUT_OF_WINDOW": 422,
    "ERR_SALES_TOTALS_INCONSISTENT": 422,
    "ERR_UNITS_EXCEED_ON_HAND": 422,
    # --- retention ---
    "ERR_BONUS_NOT_EARNED": 409,
    # --- lease ---
    "ERR_MAX_NEGOTIATION_ROUNDS": 409,
    "ERR_FIXTURE_BELOW_RESERVE": 422,
    "ERR_SURRENDER_NOTICE_SHORT": 409,
    # --- settlement ---
    "ERR_STORES_NOT_CLOSED": 409,
    "ERR_SETTLEMENT_ALREADY_OPEN": 409,
    "ERR_SETTLEMENT_BASIS_INVALID": 409,
    "ERR_LEASE_NOT_DISPOSED": 409,
    "ERR_ECONOMICS_CONFIG_INVALID": 422,
}

DEFAULT_MESSAGES = {
    "ERR_MISSING_USER_HEADER": "X-User-ID header is absent or empty",
    "ERR_UNKNOWN_ACTOR": "The supplied actor identity could not be resolved",
    "ERR_UNAUTHORIZED": "The acting role may not perform this operation",
    "ERR_STORE_SCOPE_VIOLATION": "A store manager may only address its own store",
    "ERR_SELF_APPROVAL_FORBIDDEN": "The submitting identity may not decide its own record",
    "ERR_INVALID_REQUEST": "The request body or query string is malformed",
    "ERR_INVALID_DATE_RANGE": "The supplied date interval is inverted",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id[4:].replace("_", " ").lower()
        )
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
