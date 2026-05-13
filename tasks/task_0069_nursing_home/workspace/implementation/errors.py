"""Error catalog and APIError exception."""


# Error catalog: error_id -> HTTP status
ERROR_CATALOG = {
    "ERR_AUTH_MISSING": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_VALIDATION": 422,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_WITNESS_REQUIRED": 422,
    "ERR_DRUG_INTERACTION": 409,
    "ERR_ALLERGY_CONFLICT": 409,
    "ERR_HEALTH_SCREENING_FAILED": 422,
    "ERR_VISITATION_LOCKED": 403,
    "ERR_BED_TYPE_MISMATCH": 409,
    "ERR_BED_ALREADY_OCCUPIED": 409,
    "ERR_ACTIVE_PLAN_EXISTS": 409,
    "ERR_PLAN_LEVEL_MISMATCH": 409,
    "ERR_VISIT_SLOT_CONFLICT": 409,
    "ERR_VISIT_DAILY_LIMIT": 409,
    "ERR_INVALID_SLOT_DURATION": 422,
    "ERR_TASK_RECORD_WINDOW": 422,
    "ERR_SLOT_NOT_SCHEDULED": 422,
    "ERR_SLOT_ALREADY_ADMINISTERED": 409,
    "ERR_CYCLE_COVERAGE_GAP": 422,
    "ERR_REFUND_OVER_LIMIT": 422,
    "ERR_DEPOSIT_INSUFFICIENT": 422,
    "ERR_OUTSTANDING_BALANCE": 409,
    "ERR_BILL_NOT_FINALIZED": 409,
    "ERR_DUPLICATE_PAYMENT": 409,
    "ERR_DUPLICATE_EVENT": 409,
}


class APIError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_CATALOG.get(error_id, 500)
        super().__init__(self.message)
