"""Error catalogue (PRD section 5, 35 codes) and the carrier exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = HTTP_STATUS[error_id]
        self.message = message or DEFAULT_MESSAGE.get(error_id, error_id)


HTTP_STATUS = {
    # auth and access gates
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_CONFIDENTIALITY_WALL": 403,
    "ERR_SCOPE_VIOLATION": 403,
    # existence
    "ERR_EMPLOYER_NOT_FOUND": 404,
    "ERR_SITE_NOT_FOUND": 404,
    "ERR_PROVIDER_NOT_FOUND": 404,
    "ERR_PARTICIPANT_NOT_FOUND": 404,
    "ERR_APPOINTMENT_NOT_FOUND": 404,
    "ERR_VISIT_NOT_FOUND": 404,
    "ERR_ASSESSMENT_NOT_FOUND": 404,
    "ERR_REFERRAL_NOT_FOUND": 404,
    "ERR_AWARD_NOT_FOUND": 404,
    "ERR_PERIOD_NOT_FOUND": 404,
    "ERR_RESOURCE_NOT_FOUND": 404,
    # payload
    "ERR_VALIDATION": 400,
    "ERR_INVALID_ENUM": 400,
    # concurrency and state
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_RESCHEDULE_LIMIT_REACHED": 409,
    "ERR_PERIOD_FINALIZED": 409,
    # eligibility, disclosure, credentials
    "ERR_NOT_ELIGIBLE_ON_DATE": 422,
    "ERR_AUTHORIZATION_REVOKED": 403,
    "ERR_DISCLOSURE_NOT_PERMITTED": 422,
    "ERR_PROVIDER_CREDENTIAL_LAPSED": 422,
    # scheduling
    "ERR_SITE_CLOSED": 422,
    "ERR_OUTSIDE_OPERATING_HOURS": 422,
    "ERR_STAFFING_COVERAGE_REQUIRED": 422,
    "ERR_PROVIDER_SLOT_CONFLICT": 409,
    "ERR_SLOT_CAPACITY_EXHAUSTED": 409,
    "ERR_EMPLOYER_QUOTA_EXHAUSTED": 409,
    # compliance and money
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_DUPLICATE_ELIGIBILITY": 409,
    "ERR_INCENTIVE_CAP_EXCEEDED": 422,
    "ERR_WELLNESS_BUDGET_EXCEEDED": 422,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and the role must be one of the seven declared roles.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorized for this endpoint.",
    "ERR_CONFIDENTIALITY_WALL": "An employer-side role may not touch an individual-level clinical resource.",
    "ERR_SCOPE_VIOLATION": "The caller acted outside the scope its identity grants.",
    "ERR_EMPLOYER_NOT_FOUND": "No such employer.",
    "ERR_SITE_NOT_FOUND": "No such site.",
    "ERR_PROVIDER_NOT_FOUND": "No such provider.",
    "ERR_PARTICIPANT_NOT_FOUND": "No such participant.",
    "ERR_APPOINTMENT_NOT_FOUND": "No such appointment.",
    "ERR_VISIT_NOT_FOUND": "No such visit.",
    "ERR_ASSESSMENT_NOT_FOUND": "No such health assessment.",
    "ERR_REFERRAL_NOT_FOUND": "No such referral.",
    "ERR_AWARD_NOT_FOUND": "No such incentive award.",
    "ERR_PERIOD_NOT_FOUND": "No such reporting period.",
    "ERR_RESOURCE_NOT_FOUND": "No such resource.",
    "ERR_VALIDATION": "The request body is not well formed.",
    "ERR_INVALID_ENUM": "An enum-typed field carries a value outside its declared member set.",
    "ERR_STALE_VERSION": "The supplied expected version does not match the current version.",
    "ERR_INVALID_STATE": "The requested transition is not declared from the current state.",
    "ERR_RESCHEDULE_LIMIT_REACHED": "The appointment has already been rescheduled twice.",
    "ERR_PERIOD_FINALIZED": "The governing date falls inside a finalized or closed reporting period.",
    "ERR_NOT_ELIGIBLE_ON_DATE": "The participant is not enrolled and covered on the governing date.",
    "ERR_AUTHORIZATION_REVOKED": "Disclosure authorization is not in force for this participant.",
    "ERR_DISCLOSURE_NOT_PERMITTED": "The requested disclosure is not permitted for this visit.",
    "ERR_PROVIDER_CREDENTIAL_LAPSED": "The named provider is not credentialed.",
    "ERR_SITE_CLOSED": "The site is closed on the requested service date.",
    "ERR_OUTSIDE_OPERATING_HOURS": "The appointment interval is outside the site's operating window.",
    "ERR_STAFFING_COVERAGE_REQUIRED": "No staffing shift covers the appointment interval.",
    "ERR_PROVIDER_SLOT_CONFLICT": "The provider is already occupied over the candidate interval.",
    "ERR_SLOT_CAPACITY_EXHAUSTED": "The site has no remaining slot capacity on that service date.",
    "ERR_EMPLOYER_QUOTA_EXHAUSTED": "No eligible vendor contract grants this employer capacity at this site.",
    "ERR_SEGREGATION_OF_DUTIES": "The navigator who raised a referral may not authorize it.",
    "ERR_DUPLICATE_ELIGIBILITY": "An overlapping eligibility span already exists for this member.",
    "ERR_INCENTIVE_CAP_EXCEEDED": "The award would breach the incentive program cap.",
    "ERR_WELLNESS_BUDGET_EXCEEDED": "The award would breach the employer's wellness budget.",
}

# Entity kind -> not-found error id (PRD ladder rung 4).
KIND_NOT_FOUND = {
    "employer": "ERR_EMPLOYER_NOT_FOUND",
    "site": "ERR_SITE_NOT_FOUND",
    "provider": "ERR_PROVIDER_NOT_FOUND",
    "participant": "ERR_PARTICIPANT_NOT_FOUND",
    "appointment": "ERR_APPOINTMENT_NOT_FOUND",
    "visit": "ERR_VISIT_NOT_FOUND",
    "assessment": "ERR_ASSESSMENT_NOT_FOUND",
    "referral": "ERR_REFERRAL_NOT_FOUND",
    "award": "ERR_AWARD_NOT_FOUND",
    "period": "ERR_PERIOD_NOT_FOUND",
    "contract": "ERR_RESOURCE_NOT_FOUND",
    "shift": "ERR_RESOURCE_NOT_FOUND",
    "eligibility": "ERR_RESOURCE_NOT_FOUND",
    "alt_standard": "ERR_RESOURCE_NOT_FOUND",
}
