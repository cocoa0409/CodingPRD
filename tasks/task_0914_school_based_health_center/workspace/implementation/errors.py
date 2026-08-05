"""Error catalogue (PRD section 5) and the exception used to raise them."""

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_OWNERSHIP_VIOLATION": 403,
    "ERR_VALIDATION": 400,
    "ERR_STUDENT_NOT_FOUND": 404,
    "ERR_SCHOOL_NOT_FOUND": 404,
    "ERR_CLINICIAN_NOT_FOUND": 404,
    "ERR_VISIT_NOT_FOUND": 404,
    "ERR_REFERRAL_NOT_FOUND": 404,
    "ERR_CHARGE_NOT_FOUND": 404,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_SCHOOL_SUSPENDED": 409,
    "ERR_ENROLLMENT_NOT_ACTIVE": 409,
    "ERR_CONSENT_REQUIRED": 409,
    "ERR_TELEHEALTH_CONSENT_REQUIRED": 409,
    "ERR_SELF_CONSENT_NOT_PERMITTED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_DISCIPLINE_MISMATCH": 409,
    "ERR_IMMUNIZATION_NON_COMPLIANT": 409,
    "ERR_DOSE_SEQUENCE": 409,
    "ERR_DUPLICATE_DOSE": 409,
    "ERR_INVALID_SESSION_WINDOW": 400,
    "ERR_CLINICIAN_SLOT_CONFLICT": 409,
    "ERR_SCHOOL_CAPACITY_EXCEEDED": 409,
    "ERR_NO_SHOW_TOO_EARLY": 409,
    "ERR_REINSTATEMENT_LIMIT_EXCEEDED": 409,
    "ERR_REEVALUATION_LIMIT_EXCEEDED": 409,
    "ERR_OUTREACH_LIMIT_EXCEEDED": 409,
    "ERR_RESCHEDULE_LIMIT_EXCEEDED": 409,
    "ERR_DELIVERY_ATTEMPTS_EXHAUSTED": 409,
    "ERR_ACK_WINDOW_EXPIRED": 409,
    "ERR_CLAIM_NOT_APPLICABLE": 409,
    "ERR_APPEAL_LIMIT_EXCEEDED": 409,
    "ERR_WRITE_OFF_NOT_PERMITTED": 409,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 409,
    "ERR_INVALID_REPORT_PERIOD": 400,
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline to abort with a catalogue error."""

    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = ERROR_HTTP.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
