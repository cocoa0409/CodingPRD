"""Error classes and the error catalog (id -> HTTP status)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status if http_status is not None else ERROR_STATUS.get(error_id, 400)


# Complete error catalog from PRD §5 / SCAFFOLD §1.6
ERROR_STATUS = {
    "ERR_MISSING_USER_CONTEXT": 400,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_CLINIC_NOT_FOUND": 404,
    "ERR_PATIENT_NOT_FOUND": 404,
    "ERR_SHIFT_NOT_FOUND": 404,
    "ERR_MACHINE_NOT_FOUND": 404,
    "ERR_STATION_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_SLOT_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_TRIP_NOT_FOUND": 404,
    "ERR_LAB_NOT_FOUND": 404,
    "ERR_STATEMENT_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CROSS_CLINIC_REFERENCE": 422,
    "ERR_CLINIC_SUSPENDED": 409,
    "ERR_CLINIC_HAS_ACTIVE_SESSIONS": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_ORDER_NOT_ACTIVE": 409,
    "ERR_ACTIVE_ORDER_EXISTS": 409,
    "ERR_SESSION_NOT_COMPLETED": 409,
    "ERR_SESSION_NOT_VOIDABLE": 409,
    "ERR_SESSION_NOT_SCHEDULABLE": 409,
    "ERR_DATE_NOT_ON_PATTERN": 422,
    "ERR_ISOLATION_STATION_REQUIRED": 422,
    "ERR_MODALITY_NOT_SUPPORTED": 422,
    "ERR_DIALYZER_REUSE_EXCEEDED": 409,
    "ERR_STATION_DOUBLE_BOOKED": 409,
    "ERR_TURNOVER_BUFFER_VIOLATION": 409,
    "ERR_MACHINE_IN_USE": 409,
    "ERR_MACHINE_UNAVAILABLE": 409,
    "ERR_STATION_OFFLINE": 409,
    "ERR_STATION_OCCUPIED": 409,
    "ERR_PATIENT_SUSPENDED": 409,
    "ERR_TRANSIENT_NO_STANDING_SLOT": 422,
    "ERR_STALE_PATIENT_VERSION": 412,
}
