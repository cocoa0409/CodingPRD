"""Error catalogue and the ApiError exception (PRD section 5)."""

ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": (401, "Authentication headers are missing."),
    "ERR_FORBIDDEN_ROLE": (403, "This role may not perform this operation."),
    "ERR_NOT_HOUSEHOLD_OWNER": (403, "An applicant may act only on its own household."),
    "ERR_SEGREGATION_OF_DUTIES": (
        403, "The acting user may not both prepare and dispose of this action."),
    "ERR_HOUSEHOLD_NOT_FOUND": (404, "Household not found."),
    "ERR_APPLICATION_NOT_FOUND": (404, "Application not found."),
    "ERR_INCOME_SOURCE_NOT_FOUND": (404, "Income source not found."),
    "ERR_CASE_NOT_FOUND": (404, "Assistance case not found."),
    "ERR_EXTENSION_NOT_FOUND": (404, "Time limit extension not found."),
    "ERR_WORK_ASSIGNMENT_NOT_FOUND": (404, "Work assignment not found."),
    "ERR_PARTICIPATION_REPORT_NOT_FOUND": (404, "Participation report not found."),
    "ERR_COMPLIANCE_EPISODE_NOT_FOUND": (404, "Compliance episode not found."),
    "ERR_AUTHORIZATION_NOT_FOUND": (404, "Supportive service authorization not found."),
    "ERR_OVERPAYMENT_NOT_FOUND": (404, "Overpayment not found."),
    "ERR_DIVERSION_GRANT_NOT_FOUND": (404, "Diversion grant not found."),
    "ERR_REPORTING_PERIOD_NOT_FOUND": (404, "Reporting period not found."),
    "ERR_INVALID_REQUEST": (400, "The request body or query string is invalid."),
    "ERR_STALE_CASE_VERSION": (412, "The assistance case has changed since it was read."),
    "ERR_STALE_OVERPAYMENT_VERSION": (412, "The overpayment has changed since it was read."),
    "ERR_INVALID_APPLICATION_STATE": (
        409, "The application is not in a state that allows this transition."),
    "ERR_INVALID_CASE_STATE": (
        409, "The assistance case is not in a state that allows this operation."),
    "ERR_INVALID_EXTENSION_STATE": (
        409, "The extension is not in a state that allows this transition."),
    "ERR_INVALID_ASSIGNMENT_STATE": (
        409, "The work assignment is not in a state that allows this transition."),
    "ERR_INVALID_REPORT_STATE": (
        409, "The participation report is not in a state that allows this transition."),
    "ERR_INVALID_EPISODE_STATE": (
        409, "The compliance episode is not in a state that allows this transition."),
    "ERR_INVALID_AUTHORIZATION_STATE": (
        409, "The authorization is not in a state that allows this transition."),
    "ERR_INVALID_OVERPAYMENT_STATE": (
        409, "The overpayment is not in a state that allows this operation."),
    "ERR_INVALID_PERIOD_STATE": (
        409, "The reporting period is not in a state that allows this transition."),
    "ERR_INVALID_DIVERSION_STATE": (
        409, "The diversion grant is not in a state that allows this transition."),
    "ERR_CASE_NOT_ACTIVE": (409, "The assistance case must be active for this operation."),
    "ERR_ASSIGNMENT_NOT_ACTIVE": (
        409, "The related work assignment or case posture does not permit this operation."),
    "ERR_UNVERIFIED_REPORTS_IN_QUARTER": (
        409, "Participation reports in this quarter are still unverified."),
    "ERR_TIME_LIMIT_EXHAUSTED": (422, "The household has exhausted the state time limit."),
    "ERR_CONCILIATION_NOT_COMPLETE": (422, "The conciliation period has not ended."),
    "ERR_GOOD_CAUSE_ACTIVE": (422, "Good cause has been granted for this episode."),
    "ERR_EXTENSION_LIMIT_EXCEEDED": (
        422, "The requested extension exceeds what may be granted."),
    "ERR_DIVERSION_INELIGIBILITY_ACTIVE": (
        422, "The household is inside a diversion ineligibility period."),
    "ERR_SERVICE_PERIOD_OVERLAP": (
        409, "The service period overlaps an existing authorization of the same type."),
    "ERR_DUPLICATE_ISSUANCE_MONTH": (
        409, "Assistance has already been issued for this month."),
    "ERR_DUPLICATE_REPORT_MONTH": (
        409, "A participation report already exists for this month."),
    "ERR_REPORT_MONTH_OUTSIDE_ASSIGNMENT": (
        422, "The report month does not fall inside the assignment period."),
    "ERR_SCHEDULED_HOURS_CAPACITY_EXCEEDED": (
        422, "Scheduled weekly hours exceed the allowed maximum for overlapping assignments."),
    "ERR_WORK_ASSIGNMENT_CASE_MISMATCH": (
        422, "The work assignment does not belong to the given case."),
    "ERR_PRIOR_EPISODE_MISMATCH": (
        422, "The prior episode does not belong to this case or is not sanctioned."),
    "ERR_OVERPAID_MONTH_NOT_ISSUED": (422, "A month covered by the claim was never issued."),
    "ERR_RESOURCE_LIMIT_EXCEEDED": (422, "Countable resources exceed the program limit."),
    "ERR_INELIGIBLE_ZERO_BENEFIT": (422, "The calculated benefit is zero."),
    "ERR_SUPPORTIVE_CAP_EXHAUSTED": (
        422, "No supportive service funding remains for this service type or case."),
    "ERR_RECOVERY_EXCEEDS_BALANCE": (
        422, "The recovery amount exceeds the outstanding balance."),
    "ERR_REVERSAL_EXCEEDS_RECOVERED": (
        422, "The reversal amount exceeds the amount recovered."),
    "ERR_DIVERSION_REQUIRES_BENEFIT": (
        422, "A diversion grant requires a positive determined benefit."),
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        status, default_message = ERROR_CATALOG.get(
            error_id, (400, "The request could not be processed."))
        super().__init__(message or default_message)
        self.error_id = error_id
        self.http_status = status
        self.message = message or default_message


def fail(error_id, message=None):
    raise ApiError(error_id, message)
