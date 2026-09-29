"""Error catalogue (PRD §5) and the exception type carried through the stack."""

ERROR_STATUS = {
    # authentication / authorisation
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_HOST_SITE_FORBIDDEN": 403,
    "ERR_NOT_ASSIGNED_TECHNICIAN": 403,
    # existence
    "ERR_HOST_SITE_NOT_FOUND": 404,
    "ERR_STATION_NOT_FOUND": 404,
    "ERR_PORT_NOT_FOUND": 404,
    "ERR_OUTAGE_NOT_FOUND": 404,
    "ERR_DISPATCH_NOT_FOUND": 404,
    "ERR_SPARE_PART_NOT_FOUND": 404,
    "ERR_RESERVATION_NOT_FOUND": 404,
    "ERR_UPTIME_REPORT_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_COMPLAINT_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # uniqueness
    "ERR_SITE_CODE_DUPLICATE": 409,
    "ERR_STATION_CODE_DUPLICATE": 409,
    "ERR_DISPENSER_SERIAL_DUPLICATE": 409,
    "ERR_PART_NUMBER_DUPLICATE": 409,
    # optimistic concurrency
    "ERR_STALE_PARENT_VERSION": 412,
    # state
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    # segregation of duties
    "ERR_SEGREGATION_OF_DUTIES": 409,
    # certification
    "ERR_TECHNICIAN_NOT_CERTIFIED": 422,
    # referential integrity
    "ERR_OUTAGE_PORT_MISMATCH": 409,
    "ERR_CLAIM_LINE_PORT_MISMATCH": 409,
    "ERR_COMPLAINT_PORT_MISMATCH": 409,
    "ERR_COMPLAINT_OUTAGE_MISMATCH": 409,
    # temporal
    "ERR_DETECTED_AT_IN_FUTURE": 422,
    "ERR_DETECTED_AT_BEFORE_PORT": 422,
    "ERR_DISPATCH_WINDOW_INVALID": 422,
    "ERR_DISPATCH_WINDOW_OVERLAP": 409,
    "ERR_REPORTING_PERIOD_INVALID": 422,
    "ERR_REPORTING_PERIOD_NOT_ELAPSED": 422,
    "ERR_REPORTING_PERIOD_OVERLAP": 409,
    "ERR_SESSION_WINDOW_INVALID": 422,
    # host site / commissioning
    "ERR_INVALID_ACCESS_WINDOW": 422,
    "ERR_HOST_AGREEMENT_NOT_EXECUTED": 422,
    "ERR_POWER_UPGRADE_NOT_ENERGIZED": 422,
    "ERR_PARKING_ENFORCEMENT_REQUIRED": 422,
    "ERR_PORT_COUNT_BELOW_DECLARED": 422,
    "ERR_SITE_CAPACITY_EXCEEDED": 422,
    "ERR_INTEROP_SCORE_BELOW_THRESHOLD": 422,
    # cross-entity state dependency
    "ERR_UPTIME_REPORT_NOT_ACCEPTED": 409,
    "ERR_STATION_NOT_SERVICEABLE": 409,
    "ERR_PORT_RETIRED": 409,
    # exclusion / reporting
    "ERR_EXCLUSION_CAUSE_NOT_ELIGIBLE": 422,
    "ERR_EXCLUSION_REVIEW_PENDING": 409,
    "ERR_NO_REPORTABLE_PORT_MINUTES": 422,
    # refunds
    "ERR_REFUND_BASIS_NOT_ELIGIBLE": 422,
    "ERR_REFUND_IN_FLIGHT": 409,
    "ERR_REFUND_EXCEEDS_SESSION_CHARGE": 422,
    "ERR_SESSION_CHARGE_INVALID": 422,
    # inventory / fiscal
    "ERR_RESERVATION_QTY_INVALID": 422,
    "ERR_CLAIM_LINE_ITEMS_EMPTY": 422,
    "ERR_UPTIME_BELOW_APPROVAL_THRESHOLD": 422,
    "ERR_WITHHOLD_RATE_MISMATCH": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def err(error_id, message=None):
    return ApiError(error_id, message)
