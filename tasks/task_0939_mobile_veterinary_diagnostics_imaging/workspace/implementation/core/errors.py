"""Error catalogue (PRD 5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = HTTP_BY_ERROR.get(error_id, 400)
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


HTTP_BY_ERROR = {
    # auth / authz
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_ASSIGNED_SPECIALIST": 403,
    # existence
    "ERR_CLINIC_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_EQUIPMENT_NOT_FOUND": 404,
    "ERR_SPECIALIST_NOT_FOUND": 404,
    "ERR_ROUTE_NOT_FOUND": 404,
    "ERR_STOP_NOT_FOUND": 404,
    "ERR_REFERRAL_NOT_FOUND": 404,
    "ERR_APPOINTMENT_NOT_FOUND": 404,
    "ERR_STUDY_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_RECORD_NOT_FOUND": 404,
    # request shape
    "ERR_VALIDATION": 400,
    "ERR_INVALID_ENUM": 400,
    # occ
    "ERR_STALE_VERSION": 412,
    # write gates
    "ERR_INVOICE_FINALIZED": 409,
    "ERR_CLINIC_BILLING_HOLD": 409,
    "ERR_UNIT_OUT_OF_SERVICE": 409,
    "ERR_EQUIPMENT_QUARANTINED": 409,
    "ERR_EQUIPMENT_CALIBRATION_LAPSED": 409,
    "ERR_ROUTE_FROZEN": 409,
    # pipeline applicability
    "ERR_NOT_APPLICABLE_TO_TELERAD": 422,
    "ERR_STUDY_KIND_MISMATCH": 422,
    "ERR_MOBILE_REQUIRES_ROUTE_STOP": 422,
    "ERR_TELERAD_HAS_NO_ROUTE_STOP": 422,
    # counterparty posture
    "ERR_CLINIC_INACTIVE": 409,
    "ERR_CONTRACT_NOT_ACTIVE": 409,
    "ERR_TECHNICIAN_INACTIVE": 409,
    "ERR_SPECIALIST_INACTIVE": 409,
    # state preconditions
    "ERR_ROUTE_INVALID_STATE": 409,
    "ERR_STOP_INVALID_STATE": 409,
    "ERR_REFERRAL_INVALID_STATE": 409,
    "ERR_APPOINTMENT_INVALID_STATE": 409,
    "ERR_STUDY_TERMINAL": 409,
    "ERR_STUDY_INVALID_STATE": 409,
    "ERR_TAT_CLOCK_STATE_INVALID": 409,
    "ERR_ALREADY_STAT": 409,
    "ERR_ASSIGNMENT_INVALID_STATE": 409,
    "ERR_REPORT_INVALID_STATE": 409,
    "ERR_PEER_REVIEW_INVALID_STATE": 409,
    # acquisition-side matching
    "ERR_TECHNICIAN_NOT_CERTIFIED": 422,
    "ERR_TECHNICIAN_NOT_ON_ROUTE": 409,
    "ERR_STOP_NOT_ARRIVED": 409,
    "ERR_EQUIPMENT_NOT_ON_UNIT": 422,
    "ERR_EQUIPMENT_MODALITY_MISMATCH": 422,
    "ERR_EQUIPMENT_QC_DUE": 409,
    # reading-side matching
    "ERR_SPECIALIST_MODALITY_NOT_PRIVILEGED": 422,
    "ERR_SPECIALIST_SPECIES_NOT_PRIVILEGED": 422,
    "ERR_SPECIALIST_NOT_STAT_ELIGIBLE": 422,
    "ERR_READ_ATTEMPT_CAP_EXCEEDED": 409,
    "ERR_SPECIALIST_READ_CAPACITY": 409,
    "ERR_STUDY_NOT_READ_READY": 409,
    # reporting / quality
    "ERR_REPORT_SEQUENCE_INVALID": 422,
    "ERR_ADDENDUM_WINDOW_CLOSED": 422,
    "ERR_PEER_REVIEW_SELF": 422,
    # route geometry / capacity
    "ERR_STOP_SERVICE_MINUTES_TOO_SHORT": 422,
    "ERR_STOP_OUTSIDE_SHIFT_WINDOW": 422,
    "ERR_STOP_WINDOW_CONFLICT": 409,
    "ERR_CLINIC_STOP_ALREADY_SCHEDULED": 409,
    "ERR_ROUTE_STOP_CAP_EXCEEDED": 409,
    "ERR_ROUTE_SHIFT_MINUTES_EXCEEDED": 409,
    "ERR_ROUTE_HAS_NO_STOPS": 422,
    # repeats / billing
    "ERR_REPEAT_CAP_EXCEEDED": 409,
    "ERR_REPEAT_CAUSE_NOT_SUPPORTED": 422,
    "ERR_CLINIC_MISMATCH": 422,
    "ERR_STUDY_OUTSIDE_INVOICE_PERIOD": 422,
    "ERR_STUDY_NOT_FINALIZED": 409,
    "ERR_STUDY_NON_BILLABLE": 422,
    "ERR_STUDY_ALREADY_POSTED": 409,
}

_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or invalid authentication headers.",
    "ERR_FORBIDDEN_ROLE": "The acting role may not use this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The acting identity does not own the targeted resource.",
    "ERR_VALIDATION": "The request payload failed validation.",
    "ERR_INVALID_ENUM": "A supplied value is not a member of its closed enum.",
    "ERR_STALE_VERSION": "The supplied expected version does not match the current version.",
}
