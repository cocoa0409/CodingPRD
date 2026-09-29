"""Error catalogue for the Tip Pooling Payroll API (PRD section 5)."""

ERROR_STATUS = {
    # authentication / authorization / schema
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_LOCATION_NOT_FOUND": 404,
    "ERR_EMPLOYEE_NOT_FOUND": 404,
    "ERR_POLICY_NOT_FOUND": 404,
    "ERR_PAY_PERIOD_NOT_FOUND": 404,
    "ERR_SHIFT_NOT_FOUND": 404,
    "ERR_POOL_NOT_FOUND": 404,
    "ERR_PAY_LINE_NOT_FOUND": 404,
    "ERR_DISPUTE_NOT_FOUND": 404,
    "ERR_CORRECTION_NOT_FOUND": 404,
    "ERR_RECORD_NOT_FOUND": 404,
    # state preconditions
    "ERR_SHIFT_NOT_OPEN": 409,
    "ERR_SHIFT_NOT_CLOSED": 409,
    "ERR_SHIFT_ALREADY_POOLED": 409,
    "ERR_POLICY_NOT_DRAFT": 409,
    "ERR_PAY_PERIOD_NOT_OPEN": 409,
    "ERR_PAY_PERIOD_NOT_COMPUTED": 409,
    "ERR_PENDING_CORRECTION_EXISTS": 409,
    "ERR_POOL_ALREADY_DISTRIBUTED": 409,
    "ERR_POOL_REVERSED": 409,
    "ERR_POOL_NOT_DISTRIBUTED": 409,
    "ERR_DISPUTE_NOT_OPEN": 409,
    "ERR_DISPUTE_NOT_ADJUDICATED": 409,
    "ERR_CORRECTION_NOT_PENDING": 409,
    "ERR_PAY_LINE_NOT_FINAL": 409,
    # optimistic concurrency
    "ERR_STALE_LOCATION_VERSION": 412,
    "ERR_STALE_PAY_LINE_VERSION": 412,
    # safety / compliance / regulatory
    "ERR_MANAGER_POOL_PARTICIPATION": 422,
    "ERR_POOL_TYPE_REQUIRES_NO_TIP_CREDIT": 422,
    "ERR_CC_FEE_DEDUCTION_PROHIBITED": 422,
    "ERR_CASH_WAGE_BELOW_FLOOR": 422,
    "ERR_CC_FEE_CAP_REQUIRED": 422,
    "ERR_SIDE_WORK_NOT_ELIGIBLE": 422,
    # referential integrity across aggregates
    "ERR_NO_ACTIVE_ROLE_ASSIGNMENT": 422,
    "ERR_EMPLOYEE_LOCATION_MISMATCH": 422,
    "ERR_NO_ACTIVE_POOL_POLICY": 422,
    "ERR_UNDECLARED_SHIFT_IN_POOL": 422,
    "ERR_UNDECLARED_SHIFT_IN_PERIOD": 422,
    "ERR_SERVICE_CHARGE_UNALLOCATABLE": 422,
    "ERR_SUPERSEDE_TARGET_MISMATCH": 422,
    # temporal
    "ERR_SHIFT_OVERLAP": 409,
    "ERR_PAY_PERIOD_OVERLAP": 409,
    "ERR_ASSIGNMENT_OVERLAP": 409,
    "ERR_SHIFT_FUTURE_DATE": 422,
    "ERR_BUSINESS_DATE_OUT_OF_PERIOD": 422,
    "ERR_PAY_PERIOD_LENGTH": 422,
    "ERR_EMPLOYEE_SEPARATED": 422,
    # constraint satisfaction / uniqueness
    "ERR_SIDE_WORK_EXCEEDS_SHIFT": 422,
    "ERR_POOL_DATE_DUPLICATE": 409,
    "ERR_DUPLICATE_DISPUTE_CATEGORY": 409,
    "ERR_PARTIAL_AMOUNT_INVALID": 422,
    "ERR_DUPLICATE_JOB_ROLE_CODE": 409,
    # fiscal
    "ERR_DECLARED_CHARGED_TIPS_EXCEED_CHARGED_SALES": 422,
    "ERR_CHARGED_SALES_EXCEED_GROSS_SALES": 422,
    "ERR_EMPTY_POOL_NO_CONTRIBUTIONS": 422,
    "ERR_NO_ELIGIBLE_PARTICIPANTS": 422,
    "ERR_CORRECTION_EXCEEDS_CLAIM": 422,
    "ERR_CORRECTION_EXCEEDS_OBLIGATION": 422,
}


class ApiError(Exception):
    """A business/validation failure carrying the catalogue error id."""

    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)
        super().__init__(self.message)


def _default_message(error_id):
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return "Request rejected: %s." % words


def invalid(message):
    return ApiError("ERR_INVALID_REQUEST", message)
