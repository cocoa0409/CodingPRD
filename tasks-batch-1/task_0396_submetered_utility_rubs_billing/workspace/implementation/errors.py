"""Error catalogue and the ApiError exception (PRD §5 / SCAFFOLD §1.6)."""

# Maps error_id -> default HTTP status code.
ERROR_CATALOG = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 401,
    "ERR_FORBIDDEN_FOR_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_NOT_STATEMENT_OWNER": 403,
    "ERR_INVALID_STATE": 409,
    "ERR_UNIT_NOT_FOUND": 404,
    "ERR_DUPLICATE_SERIAL": 409,
    "ERR_METER_ASSIGNMENT_OVERLAP": 409,
    "ERR_METER_HAS_PENDING_READS": 409,
    "ERR_READING_OUT_OF_RANGE": 409,
    "ERR_CYCLE_NOT_OPEN": 409,
    "ERR_DUPLICATE_UNIT_NUMBER": 409,
    "ERR_LEASE_OCCUPANCY_OVERLAP": 409,
    "ERR_INVALID_MOVE_OUT_DATE": 422,
    "ERR_MOVE_OUT_NOT_DUE": 409,
    "ERR_LEASE_HAS_OPEN_BALANCE": 409,
    "ERR_VENDOR_BILL_NOT_APPROVED": 409,
    "ERR_VENDOR_BILL_IN_USE": 409,
    "ERR_READS_NOT_VALIDATED": 409,
    "ERR_NO_BILLABLE_LEASES": 409,
    "ERR_CYCLE_HAS_OPEN_DISPUTES": 409,
    "ERR_CYCLE_CLOSED": 409,
    "ERR_NOT_YET_DELINQUENT": 409,
    "ERR_NOT_YET_COLLECTIONS": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_PAYMENT_EXCEEDS_BALANCE": 409,
    "ERR_CREDIT_EXCEEDS_DUE": 409,
    "ERR_MAX_REOPENS_REACHED": 409,
}


class ApiError(Exception):
    """Raised anywhere in the request lifecycle to abort with a standard error."""

    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_CATALOG.get(error_id, 400)
        super().__init__(self.message)
