"""Error catalogue for the False Alarm Reduction / Alarm Permit Program API.

Every error_id and HTTP status below is taken verbatim from PRD.md section 5
and SCAFFOLD.yaml `errors`.
"""

ERROR_STATUS = {
    # ---- auth / RBAC -----------------------------------------------------
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_UNKNOWN_ROLE": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NOT_DOCKET_OFFICER": 403,
    # ---- field shape / paging -------------------------------------------
    "ERR_MISSING_REQUIRED_FIELD": 422,
    "ERR_INVALID_FIELD_VALUE": 422,
    "ERR_INVALID_PAGINATION": 422,
    # ---- existence -------------------------------------------------------
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_FEE_SCHEDULE_NOT_FOUND": 404,
    "ERR_ALARM_COMPANY_NOT_FOUND": 404,
    "ERR_ALARM_SITE_NOT_FOUND": 404,
    "ERR_SITE_CONTACT_NOT_FOUND": 404,
    "ERR_ALARM_SYSTEM_NOT_FOUND": 404,
    "ERR_ALARM_PERMIT_NOT_FOUND": 404,
    "ERR_DISPATCH_REQUEST_NOT_FOUND": 404,
    "ERR_FALSE_ALARM_INCIDENT_NOT_FOUND": 404,
    "ERR_HEARING_DOCKET_NOT_FOUND": 404,
    "ERR_APPEAL_NOT_FOUND": 404,
    "ERR_SUSPENSION_ORDER_NOT_FOUND": 404,
    "ERR_PENALTY_INVOICE_NOT_FOUND": 404,
    "ERR_PAYMENT_RECORD_NOT_FOUND": 404,
    "ERR_PAYMENT_ALLOCATION_NOT_FOUND": 404,
    "ERR_COMPLIANCE_REPORT_NOT_FOUND": 404,
    # ---- stale revision guards ------------------------------------------
    "ERR_STALE_ALARM_SITE_VERSION": 412,
    "ERR_STALE_PENALTY_INVOICE_VERSION": 412,
    "ERR_STALE_ALARM_SYSTEM_VERSION": 412,
    "ERR_STALE_ALARM_PERMIT_VERSION": 412,
    "ERR_STALE_FALSE_ALARM_INCIDENT_VERSION": 412,
    "ERR_STALE_HEARING_DOCKET_VERSION": 412,
    # ---- state / business ------------------------------------------------
    "ERR_INVALID_STATE": 409,
    "ERR_OPEN_DISPATCH_REQUEST_EXISTS": 409,
    "ERR_INCIDENT_ALREADY_REPORTED": 409,
    "ERR_DOCKET_NOT_OPEN": 409,
    "ERR_DOCKET_EMPTY": 409,
    "ERR_INVOICE_WRITTEN_OFF": 409,
    "ERR_COMPANY_NOT_SYSTEM_MONITOR": 409,
    "ERR_EXEMPT_CAUSE_NOT_RECOGNIZED": 422,
    "ERR_EXEMPT_CAUSE_MUST_BE_EXEMPT": 422,
    "ERR_COMPANY_DISPATCH_PRIVILEGE_SUSPENDED": 403,
    "ERR_POLICE_RESPONSE_SUSPENDED": 409,
    "ERR_INSUFFICIENT_ECV_CONTACTS": 409,
    "ERR_ECV_REQUIREMENT_NOT_MET": 422,
    "ERR_VERIFIED_RESPONSE_NOT_CONFIRMED": 409,
    "ERR_APPEAL_WINDOW_CLOSED": 409,
    "ERR_HEARING_SESSION_IN_PAST": 422,
    "ERR_HEARING_SESSION_NOT_STARTED": 409,
    "ERR_INSPECTION_EVIDENCE_STALE": 409,
    "ERR_SUSPENSION_EFFECTIVE_DATE_INVALID": 422,
    "ERR_PAYMENT_VOID_WINDOW_CLOSED": 409,
    "ERR_APPEAL_ALREADY_PENDING": 409,
    "ERR_REHEARING_NOT_ELIGIBLE": 409,
    "ERR_DOCKET_CAPACITY_EXCEEDED": 409,
    "ERR_DOCKET_SESSION_OVERLAP": 409,
    "ERR_SUSPENSION_PERIOD_OVERLAP": 409,
    "ERR_DUPLICATE_ADDRESS_KEY": 409,
    "ERR_ACTIVE_PERMIT_EXISTS": 409,
    "ERR_NO_ACTIVE_FEE_SCHEDULE": 409,
    "ERR_DUPLICATE_CONTACT_PRIORITY": 409,
    "ERR_CONTACT_ROSTER_MINIMUM": 409,
    "ERR_REPORT_PERIOD_OVERLAP": 409,
    "ERR_NO_REPORTABLE_VARIANCE": 409,
    "ERR_CORRECTION_LIMIT_REACHED": 409,
    "ERR_SUSPENSION_BASIS_NO_LONGER_MET": 409,
    "ERR_ECV_ATTESTATION_REQUIRED": 422,
    "ERR_COMPANY_REINSTATEMENT_NOT_EARNED": 409,
    "ERR_INVOICE_UNDER_APPEAL": 409,
    "ERR_REFERRAL_CRITERIA_NOT_MET": 409,
    "ERR_SITE_BALANCE_DELINQUENT": 402,
    "ERR_PERMIT_RENEWAL_BLOCKED": 409,
    "ERR_OUTSTANDING_BALANCE_BLOCKS_REINSTATEMENT": 402,
    "ERR_ADJUSTMENT_EXCEEDS_OUTSTANDING": 422,
    "ERR_ALLOCATION_MISMATCH": 422,
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline; rendered by the Flask handler."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    body = error_id[4:] if error_id.startswith("ERR_") else error_id
    return body.replace("_", " ").capitalize() + "."


def err(error_id, message=None):
    return ApiError(error_id, message)
