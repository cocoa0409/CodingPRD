"""Error catalogue (SCAFFOLD Table 1.6 / PRD section 5) and the ApiError type."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP_STATUS[error_id]
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_HTTP_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_FAMILY_NOT_FOUND": 404,
    "ERR_CHILD_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_PHYSICIAN_NOT_FOUND": 404,
    "ERR_MEMBERSHIP_NOT_FOUND": 404,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_ENUM": 400,
    "ERR_INVALID_DATE_RANGE": 400,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_MEMBERSHIP_NOT_ACTIVE": 409,
    "ERR_ENROLLMENT_INVOICE_UNPAID": 409,
    "ERR_POLICY_INACTIVE": 409,
    "ERR_LICENSURE_NOT_COVERED": 422,
    "ERR_MODALITY_NOT_ALLOWED": 422,
    "ERR_FUTURE_DATED": 422,
    "ERR_SCHEDULE_CONFLICT": 409,
    "ERR_ENCOUNTER_OVERLAP": 409,
    "ERR_DUPLICATE_MEMBERSHIP": 409,
    "ERR_DUPLICATE_WAITLIST_ENTRY": 409,
    "ERR_PANEL_CAPACITY_EXCEEDED": 409,
    "ERR_RESCHEDULE_LIMIT_REACHED": 409,
    "ERR_ROUTE_NOT_ADJUDICABLE": 422,
    "ERR_BALANCE_BILLING_BLOCKED": 422,
    "ERR_FORM_GATE_NOT_MET": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or invalid.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorised for this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The caller does not own the targeted resource.",
    "ERR_SEGREGATION_OF_DUTIES": "The adjudicating caller may not be the submitting caller.",
    "ERR_FAMILY_NOT_FOUND": "The referenced family does not exist.",
    "ERR_CHILD_NOT_FOUND": "The referenced child does not exist.",
    "ERR_PLAN_NOT_FOUND": "The referenced membership plan does not exist.",
    "ERR_PHYSICIAN_NOT_FOUND": "The referenced physician does not exist.",
    "ERR_MEMBERSHIP_NOT_FOUND": "The referenced membership does not exist.",
    "ERR_RESOURCE_NOT_FOUND": "The referenced resource does not exist.",
    "ERR_VALIDATION": "The request payload failed validation.",
    "ERR_INVALID_ENUM": "An enum-typed field carries a value outside its declared member set.",
    "ERR_INVALID_DATE_RANGE": "A supplied date or datetime falls outside the permitted range.",
    "ERR_STALE_VERSION": "The supplied version expectation does not match the current version.",
    "ERR_INVALID_STATE": "The resource's current state does not permit this transition.",
    "ERR_MEMBERSHIP_NOT_ACTIVE": "The governing membership is not ACTIVE.",
    "ERR_ENROLLMENT_INVOICE_UNPAID": "The household's invoice standing forbids this operation.",
    "ERR_POLICY_INACTIVE": "The insurance policy is not ACTIVE.",
    "ERR_LICENSURE_NOT_COVERED": "The responsible physician is not licensed in the patient's state.",
    "ERR_MODALITY_NOT_ALLOWED": "This encounter type may not be delivered with this modality.",
    "ERR_FUTURE_DATED": "A clinically dated field lies in the future.",
    "ERR_SCHEDULE_CONFLICT": "The consult interval collides with another scheduled booking.",
    "ERR_ENCOUNTER_OVERLAP": "The encounter interval overlaps another scheduled encounter for this child.",
    "ERR_DUPLICATE_MEMBERSHIP": "The child already holds a living membership.",
    "ERR_DUPLICATE_WAITLIST_ENTRY": "A conflicting row already exists.",
    "ERR_PANEL_CAPACITY_EXCEEDED": "The physician's panel cannot absorb this candidate's slot weight.",
    "ERR_RESCHEDULE_LIMIT_REACHED": "The booking has already been rescheduled the maximum number of times.",
    "ERR_ROUTE_NOT_ADJUDICABLE": "Only insurance-routed lines can be adjudicated.",
    "ERR_BALANCE_BILLING_BLOCKED": "The declared patient responsibility exceeds the permitted ceiling.",
    "ERR_FORM_GATE_NOT_MET": "A blocked form request must be rechecked before issuance.",
}
