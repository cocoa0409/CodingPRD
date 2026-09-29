"""Error catalogue and the ApiError exception (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# error_id -> (http_status, default message)
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": (401, "Authentication headers are required."),
    "ERR_UNAUTHORIZED": (403, "Role is not permitted to perform this operation."),
    "ERR_FEE_PROGRAM_NOT_FOUND": (404, "Fee program not found."),
    "ERR_FACILITY_CATEGORY_NOT_FOUND": (404, "Facility category not found."),
    "ERR_FEE_STUDY_NOT_FOUND": (404, "Fee study not found."),
    "ERR_NEXUS_COMPONENT_NOT_FOUND": (404, "Nexus component not found."),
    "ERR_DEVELOPMENT_APPLICATION_NOT_FOUND": (404, "Development application not found."),
    "ERR_CREDIT_CLAIM_NOT_FOUND": (404, "Credit claim not found."),
    "ERR_DEFERRAL_AGREEMENT_NOT_FOUND": (404, "Deferral agreement not found."),
    "ERR_PROTEST_FILING_NOT_FOUND": (404, "Protest filing not found."),
    "ERR_FUND_LEDGER_ENTRY_NOT_FOUND": (404, "Fund ledger entry not found."),
    "ERR_INVALID_REQUEST": (422, "Request payload is invalid."),
    "ERR_INVALID_REFERENCE": (404, "Referenced entity does not exist."),
    "ERR_PROGRAM_SCOPE_MISMATCH": (422, "Fee study and facility category belong to different fee programs."),
    "ERR_NOT_APPLICATION_OWNER": (403, "Only the submitting developer may act on this application."),
    "ERR_STALE_PROGRAM_VERSION": (412, "Fee program has changed since it was read."),
    "ERR_STALE_APPLICATION_VERSION": (412, "Development application has changed since it was read."),
    "ERR_STALE_CATEGORY_VERSION": (412, "Facility category has changed since it was read."),
    "ERR_SEGREGATION_OF_DUTIES": (409, "The user who certified the nexus findings may not adopt the study."),
    "ERR_REPORT_PREPARER_CONFLICT": (409, "A user who authorized expenditures in the fiscal year may not file its annual report."),
    "ERR_STUDY_INVALID_STATE": (409, "Fee study is not in a state that allows this operation."),
    "ERR_COMPONENT_ALLOCATION_STALE": (409, "Every nexus component must be allocated with an adopted fee schedule."),
    "ERR_STUDY_HAS_NO_COMPONENTS": (409, "Fee study has no nexus components to certify."),
    "ERR_PROTEST_INVALID_STATE": (409, "Protest filing cannot be withdrawn in its current state."),
    "ERR_NO_EFFECTIVE_STUDY": (409, "Program has no effective fee study."),
    "ERR_APPLICATION_INVALID_STATE": (409, "Development application is not in a state that allows this operation."),
    "ERR_REASSESSMENT_REQUIRED": (409, "Application must be re-assessed against the current effective fee schedule first."),
    "ERR_CLAIM_INVALID_STATE": (409, "Credit claim has already been decided."),
    "ERR_DEFERRAL_INVALID_STATE": (409, "Deferral agreement cannot be decided in this state."),
    "ERR_FUND_REFUND_OBLIGATION_PENDING": (409, "Outstanding statutory refund obligation must be discharged before further expenditure."),
    "ERR_LEDGER_ENTRY_INVALID_STATE": (409, "Ledger entry is not refundable in its current state."),
    "ERR_CO_BLOCKED_UNPAID": (409, "Certificate of occupancy is blocked until the impact fee obligation is satisfied."),
    "ERR_REPORT_ALREADY_FILED": (409, "Annual report for this fiscal year has already been filed."),
    "ERR_DUPLICATE_JURISDICTION_CODE": (409, "Jurisdiction code is already in use."),
    "ERR_DUPLICATE_CATEGORY_CODE": (409, "Facility category code already exists in this program."),
    "ERR_DUPLICATE_NEXUS_COMPONENT": (409, "Fee study already prices this facility category."),
    "ERR_DUPLICATE_SCHEDULE_ITEM": (409, "Fee schedule line already exists for this land use category."),
    "ERR_DUPLICATE_PERMIT_NUMBER": (409, "Permit number already exists in this program."),
    "ERR_UNIT_BASIS_MISMATCH": (422, "Unit basis is not valid for this land use category."),
    "ERR_HORIZON_OVERLAP": (409, "Projection horizon overlaps an existing component for this facility category."),
    "ERR_NOTICE_WINDOW_OVERLAP": (409, "Another fee study is already inside its statutory notice window."),
    "ERR_NOTICE_PERIOD_TOO_SHORT": (422, "Notice period is shorter than the statutory minimum."),
    "ERR_PROTEST_WINDOW_OPEN": (409, "Protest window has not closed yet."),
    "ERR_EFFECTIVE_DATE_NOT_REACHED": (409, "Statutory effective date has not been reached."),
    "ERR_DEFERRAL_DUE_DATE_INVALID": (422, "Requested deferral due date must be in the future."),
    "ERR_FISCAL_YEAR_NOT_COMPLETE": (409, "Fiscal year has not closed yet."),
    "ERR_CREDIT_CATEGORY_NOT_IN_STUDY": (422, "Claimed facility category is not priced by the effective fee study."),
    "ERR_ZERO_DEMAND_UNITS": (422, "Component has no demand units to allocate cost across."),
    "ERR_NEXUS_RATIO_INSUFFICIENT": (409, "Planned capacity does not cover projected growth demand; the rational nexus fails."),
    "ERR_NO_APPLICABLE_FEE_SCHEDULE": (409, "Effective fee schedule has no line for this land use category."),
    "ERR_INSUFFICIENT_SECURITY": (422, "Offered security does not cover the deferred fee."),
    "ERR_PAYMENT_AMOUNT_MISMATCH": (422, "Payment must settle the outstanding balance exactly."),
    "ERR_INSUFFICIENT_FUND_BALANCE": (422, "Expenditure exceeds the expendable fund balance."),
    "ERR_REFUND_NOT_ELIGIBLE": (422, "Ledger entry has no refundable amount."),
}


def api_error(error_id, message=None):
    status, default_message = ERROR_CATALOG[error_id]
    return ApiError(error_id, status, message or default_message)


def raise_error(error_id, message=None):
    raise api_error(error_id, message)
