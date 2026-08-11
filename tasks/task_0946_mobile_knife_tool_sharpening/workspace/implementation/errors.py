"""Error catalogue (PRD section 5) and the exception used to raise them."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP[error_id]
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_HTTP = {
    # --- authentication and authorization ---
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_ACCOUNT_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- existence ---
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_PLAN_TIER_NOT_FOUND": 404,
    "ERR_SUBSCRIPTION_NOT_FOUND": 404,
    "ERR_ITEM_CLASS_SPEC_NOT_FOUND": 404,
    "ERR_SERVICE_REQUEST_NOT_FOUND": 404,
    "ERR_REQUEST_ITEM_NOT_FOUND": 404,
    "ERR_TECHNICIAN_NOT_FOUND": 404,
    "ERR_VAN_NOT_FOUND": 404,
    "ERR_ROUTE_RUN_NOT_FOUND": 404,
    "ERR_ROUTE_STOP_NOT_FOUND": 404,
    "ERR_LOCKER_COMPARTMENT_NOT_FOUND": 404,
    "ERR_BENCH_DAY_NOT_FOUND": 404,
    "ERR_LOANER_UNIT_NOT_FOUND": 404,
    "ERR_LOANER_ISSUE_NOT_FOUND": 404,
    "ERR_WARRANTY_CLAIM_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_INVOICE_LINE_NOT_FOUND": 404,
    "ERR_PAYMENT_NOT_FOUND": 404,
    "ERR_ALLOWANCE_ENTRY_NOT_FOUND": 404,
    # --- request shape ---
    "ERR_VALIDATION": 400,
    "ERR_INVALID_ENUM": 422,
    "ERR_VALUE_OUT_OF_RANGE": 422,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_ACCESS_CODE_INVALID": 403,
    # --- global write gates ---
    "ERR_ACCOUNT_SUSPENDED": 409,
    "ERR_CREDIT_LIMIT_BLOCKED": 402,
    "ERR_STALE_VERSION": 412,
    # --- state ---
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_RUN_NOT_MUTABLE": 409,
    "ERR_REQUEST_NOT_MUTABLE": 409,
    "ERR_SUBSCRIPTION_NOT_ACTIVE": 409,
    "ERR_INVOICE_NOT_PAYABLE": 409,
    "ERR_ITEM_NOT_IN_CUSTODY": 409,
    "ERR_BENCH_DAY_DATE_MISMATCH": 409,
    "ERR_LOCKER_HOLD_EXPIRED": 409,
    # --- safety ---
    "ERR_CERTIFICATION_MISSING": 422,
    "ERR_AUTHORIZATION_REQUIRED": 409,
    "ERR_LOCKER_VALUE_AUTHORIZATION_REQUIRED": 409,
    # --- referential ---
    "ERR_ITEM_CLASS_MISMATCH": 422,
    "ERR_STOP_ACCOUNT_MISMATCH": 422,
    "ERR_CLAIM_ITEM_ACCOUNT_MISMATCH": 422,
    "ERR_LOANER_NOT_ELIGIBLE": 422,
    "ERR_INVOICE_SCOPE_MISMATCH": 422,
    # --- temporal ---
    "ERR_DATE_IN_PAST": 422,
    "ERR_WINDOW_OUT_OF_DAY": 422,
    "ERR_WINDOW_OVERLAP": 409,
    "ERR_LOCKER_TURNAROUND_CONFLICT": 409,
    "ERR_SKIP_WINDOW_CLOSED": 409,
    "ERR_CADENCE_CHANGE_TOO_LATE": 409,
    "ERR_WARRANTY_WINDOW_EXPIRED": 409,
    # --- constraints ---
    "ERR_ITEM_LIMIT_EXCEEDED": 422,
    "ERR_RESUBMIT_CAP_REACHED": 409,
    "ERR_SPILL_LIMIT_REACHED": 409,
    "ERR_COMPARTMENT_SIZE_UNFIT": 422,
    "ERR_DUPLICATE_ACTIVE_SUBSCRIPTION": 409,
    "ERR_DUPLICATE_ITEM_CLASS_SPEC": 409,
    "ERR_DUPLICATE_BENCH_DAY": 409,
    "ERR_DUPLICATE_DRAFT_INVOICE": 409,
    "ERR_DUPLICATE_INVOICE": 409,
    "ERR_NO_AVAILABLE_COMPARTMENT": 409,
    "ERR_NO_ELIGIBLE_RUN": 409,
    "ERR_LOANER_STOCK_EXHAUSTED": 409,
    # --- fiscal ---
    "ERR_STOP_CAP_EXCEEDED": 409,
    "ERR_RUN_MINUTES_EXCEEDED": 409,
    "ERR_BENCH_CAPACITY_EXCEEDED": 409,
    "ERR_EMPTY_INVOICE": 409,
    "ERR_OVERPAYMENT": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or carry an unknown role.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorized for this endpoint.",
    "ERR_NOT_ACCOUNT_OWNER": "The caller does not own the target resource.",
    "ERR_SEGREGATION_OF_DUTIES": "The deciding technician assessed the claimed item.",
    "ERR_VALIDATION": "A required field is missing or has the wrong type.",
    "ERR_INVALID_ENUM": "An enum field carries an undeclared member.",
    "ERR_VALUE_OUT_OF_RANGE": "A numeric or temporal field is outside its declared range.",
    "ERR_INVALID_PAGINATION": "limit must be within [1, 100] and offset must be at least 0.",
    "ERR_ACCESS_CODE_INVALID": "The supplied access code does not match.",
    "ERR_ACCOUNT_SUSPENDED": "The account is suspended.",
    "ERR_CREDIT_LIMIT_BLOCKED": "The account's outstanding balance exceeds its credit limit.",
    "ERR_STALE_VERSION": "The supplied expected version does not match the current version.",
    "ERR_ALREADY_TERMINAL": "The target entity is already in a terminal state.",
    "ERR_INVALID_STATE": "The requested transition is not available from the current state.",
}

# Entity name -> not-found error id, used by path and body existence rungs.
NOT_FOUND = {
    "Account": "ERR_ACCOUNT_NOT_FOUND",
    "PlanTier": "ERR_PLAN_TIER_NOT_FOUND",
    "Subscription": "ERR_SUBSCRIPTION_NOT_FOUND",
    "ItemClassSpec": "ERR_ITEM_CLASS_SPEC_NOT_FOUND",
    "ServiceRequest": "ERR_SERVICE_REQUEST_NOT_FOUND",
    "RequestItem": "ERR_REQUEST_ITEM_NOT_FOUND",
    "Technician": "ERR_TECHNICIAN_NOT_FOUND",
    "Van": "ERR_VAN_NOT_FOUND",
    "RouteRun": "ERR_ROUTE_RUN_NOT_FOUND",
    "RouteStop": "ERR_ROUTE_STOP_NOT_FOUND",
    "LockerCompartment": "ERR_LOCKER_COMPARTMENT_NOT_FOUND",
    "BenchDay": "ERR_BENCH_DAY_NOT_FOUND",
    "LoanerUnit": "ERR_LOANER_UNIT_NOT_FOUND",
    "LoanerIssue": "ERR_LOANER_ISSUE_NOT_FOUND",
    "WarrantyClaim": "ERR_WARRANTY_CLAIM_NOT_FOUND",
    "Invoice": "ERR_INVOICE_NOT_FOUND",
    "InvoiceLine": "ERR_INVOICE_LINE_NOT_FOUND",
    "Payment": "ERR_PAYMENT_NOT_FOUND",
    "AllowanceLedgerEntry": "ERR_ALLOWANCE_ENTRY_NOT_FOUND",
}
