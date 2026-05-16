"""Custom exception class and error definitions for the API."""


class APIError(Exception):
    """Custom exception carrying error_id, message, and http_status."""

    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error catalog: maps error_id to (http_status, default_message)
ERROR_CATALOG = {
    "ERR_AUTH_REQUIRED": (401, "Missing or malformed X-User-ID / X-User-Role headers"),
    "ERR_FORBIDDEN": (403, "Role not permitted for the requested operation"),
    "ERR_NOT_FOUND": (404, "Resource not found"),
    "ERR_NOT_APPLICATION_OWNER": (403, "Applicant does not own this application"),
    "ERR_INVALID_STATE": (409, "Target resource is not in a state from which the requested transition is allowed"),
    "ERR_STALE_VERSION": (409, "Provided version does not equal current stored version"),
    "ERR_MISSING_PRIMARY_FILER": (422, "Application must have exactly one PRIMARY_FILER HouseholdMember"),
    "ERR_COVERAGE_YEAR_INVALID": (422, "coverage_year must equal current_year or current_year+1"),
    "ERR_OUTSIDE_ENROLLMENT_WINDOW": (409, "Application.enrollment_window is CLOSED"),
    "ERR_PLAN_STATE_MISMATCH": (422, "PlanVariant's parent Plan filing_state or coverage_year does not match the Application"),
    "ERR_CSR_VARIANT_MISMATCH": (422, "PlanVariant.csr_level does not match Application.csr_eligibility"),
    "ERR_OUTSIDE_SEP_WINDOW": (422, "Enrollment coverage_start_date does not fall inside an open SEP window or OEP"),
    "ERR_MAGI_NEGATIVE": (422, "Household-level total_magi_cents cannot be negative"),
    "ERR_NO_BENCHMARK_PLAN": (422, "No benchmark Silver plan exists for the Application's filing_state and coverage_year"),
    "ERR_ENROLLMENT_ALREADY_EXISTS": (409, "Enrollment already exists for the (application_id, coverage_year) pair"),
    "ERR_PAYMENT_INSUFFICIENT": (422, "Payment amount_cents is less than PremiumInvoice.net_amount_cents"),
    "ERR_BENCHMARK_CONFLICT": (409, "Another active Plan already holds is_benchmark_silver=true for that (filing_state, coverage_year)"),
    "ERR_SEP_WINDOW_EXPIRED": (422, "SEPEvent.event_date is more than 60 calendar days before now at verify time"),
    "ERR_SEP_CONFLICT": (409, "Multiple SEPEvents race for governance of an Enrollment effective_date"),
    "ERR_INVOICE_ALREADY_PAID": (409, "PremiumInvoice.status is no longer ISSUED"),
    "ERR_DEPENDENT_AGE_INVALID": (422, "DEPENDENT date_of_birth implies age >= 26 at coverage_year start"),
}


def raise_error(error_id: str, message: str = None):
    http_status, default_msg = ERROR_CATALOG[error_id]
    raise APIError(error_id, message or default_msg, http_status)
