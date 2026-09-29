"""Error catalog (PRD section 5 / SCAFFOLD 1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else ERROR_STATUS.get(error_id, 400)
        self.message = message if message else default_message(error_id)


def default_message(error_id):
    known = _DEFAULT_MESSAGE.get(error_id)
    if known:
        return known
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return (words[:1].upper() + words[1:] + ".") if words else error_id


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_STUDY_NOT_FOUND": 404,
    "ERR_ANALYSIS_NOT_FOUND": 404,
    "ERR_COVERAGE_ITEM_NOT_FOUND": 404,
    "ERR_CALENDAR_NOT_FOUND": 404,
    "ERR_CALENDAR_VISIT_NOT_FOUND": 404,
    "ERR_ROUTE_NOT_FOUND": 404,
    "ERR_SUBJECT_NOT_FOUND": 404,
    "ERR_SUBJECT_VISIT_NOT_FOUND": 404,
    "ERR_CHARGE_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_FINDING_NOT_FOUND": 404,
    "ERR_AMENDMENT_NOT_FOUND": 404,
    "ERR_STALE_STUDY_VERSION": 412,
    "ERR_STALE_COVERAGE_ANALYSIS_VERSION": 412,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_ANALYSIS_NOT_EDITABLE": 409,
    "ERR_ANALYSIS_NOT_UNDER_REVIEW": 409,
    "ERR_CALENDAR_NOT_DRAFT": 409,
    "ERR_CHARGE_ALREADY_ROUTED": 409,
    "ERR_CHARGE_NOT_BILLED_TO_PAYER": 409,
    "ERR_INVOICE_NOT_SUBMITTABLE": 409,
    "ERR_FINDING_NOT_OPEN": 409,
    "ERR_FINDING_NOT_RESPONDED": 409,
    "ERR_AMENDMENT_NOT_SUBMITTED": 409,
    "ERR_SUBJECT_NOT_SCREENING": 409,
    "ERR_STUDY_NOT_OPEN_TO_ACCRUAL": 409,
    "ERR_BUDGET_NOT_EXECUTED": 409,
    "ERR_CALENDAR_NOT_PUBLISHED": 409,
    "ERR_STALE_CALENDAR_GENERATION": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_QCT_BASIS_UNSUPPORTED": 422,
    "ERR_REGISTRY_NUMBER_REQUIRED": 422,
    "ERR_QCT_DOWNGRADE_BLOCKED": 409,
    "ERR_ROUTINE_CARE_REQUIRES_QCT": 422,
    "ERR_QCT_DETERMINATION_REQUIRED": 409,
    "ERR_STUDY_BILLING_BLOCKED": 409,
    "ERR_PAYER_BILLING_BLOCKED_NO_QCT": 409,
    "ERR_NO_EFFECTIVE_ANALYSIS": 409,
    "ERR_CHARGE_CODE_NOT_IN_COVERAGE_ANALYSIS": 422,
    "ERR_ITEM_ANALYSIS_MISMATCH": 422,
    "ERR_CALENDAR_VISIT_NOT_ON_CONSENTED_CALENDAR": 422,
    "ERR_ROUTING_CONTRADICTS_COVERAGE": 422,
    "ERR_DUPLICATE_PROTOCOL_NUMBER": 409,
    "ERR_DUPLICATE_ITEM_CODE": 409,
    "ERR_DUPLICATE_SEQUENCE_INDEX": 409,
    "ERR_DUPLICATE_VISIT_ROUTE": 409,
    "ERR_DUPLICATE_SUBJECT_NUMBER": 409,
    "ERR_OPEN_ANALYSIS_EXISTS": 409,
    "ERR_RETURN_LIMIT_EXCEEDED": 409,
    "ERR_PROMOTIONAL_MUST_BE_ZERO_COST": 422,
    "ERR_INVOICEABLE_ITEM_NOT_VISIT_ROUTABLE": 422,
    "ERR_UNROUTED_PER_PATIENT_ITEM": 422,
    "ERR_VISIT_WINDOW_OVERLAP": 409,
    "ERR_VISIT_DATE_OUTSIDE_WINDOW": 422,
    "ERR_AMENDMENT_NOT_YET_EFFECTIVE": 409,
    "ERR_RESEARCH_VISIT_DAILY_CAPACITY_EXCEEDED": 409,
    "ERR_NO_PUBLISHED_CALENDAR_FOR_BASIS": 422,
    "ERR_NO_INVOICEABLE_CHARGES": 409,
    "ERR_REMITTANCE_AMOUNT_INVALID": 422,
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}

_DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and the role must be a declared role.",
    "ERR_UNAUTHORIZED": "The acting role is not authorized for this endpoint.",
    "ERR_INVALID_REQUEST": "The request body is invalid.",
    "ERR_INVALID_PAGINATION": "limit must be between 1 and 100 and offset must not be negative.",
    "ERR_STUDY_NOT_FOUND": "Study not found.",
    "ERR_ANALYSIS_NOT_FOUND": "Coverage analysis not found.",
    "ERR_COVERAGE_ITEM_NOT_FOUND": "Coverage item not found.",
    "ERR_CALENDAR_NOT_FOUND": "Study calendar not found.",
    "ERR_CALENDAR_VISIT_NOT_FOUND": "Calendar visit not found.",
    "ERR_ROUTE_NOT_FOUND": "Visit charge route not found.",
    "ERR_SUBJECT_NOT_FOUND": "Study subject not found.",
    "ERR_SUBJECT_VISIT_NOT_FOUND": "Subject visit not found.",
    "ERR_CHARGE_NOT_FOUND": "Charge not found.",
    "ERR_INVOICE_NOT_FOUND": "Sponsor invoice not found.",
    "ERR_FINDING_NOT_FOUND": "Audit finding not found.",
    "ERR_AMENDMENT_NOT_FOUND": "Amendment not found.",
    "ERR_STALE_STUDY_VERSION": "expected_study_version does not match the study's current version.",
    "ERR_STALE_COVERAGE_ANALYSIS_VERSION": "expected_coverage_analysis_version does not match the analysis' current version.",
    "ERR_INVALID_STATE_TRANSITION": "The requested transition is not allowed from the current state.",
}
