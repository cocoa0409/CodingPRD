"""Error catalog (PRD section 5 / scaffold 1.6)."""


ERROR_CATALOG = {
    "ERR_INVALID_REQUEST": (400, "The request body is missing a required field or contains an invalid value"),
    "ERR_UNAUTHENTICATED": (401, "Authentication headers are missing or the role is not recognized"),
    "ERR_ROLE_NOT_PERMITTED": (403, "This role may not perform this operation"),
    "ERR_NOT_RESOURCE_OWNER": (403, "The caller does not own this resource"),
    "ERR_SEGREGATION_OF_DUTIES": (403, "The operator who submitted this adoption may not approve it"),
    "ERR_TERM_NOT_FOUND": (404, "Academic term not found"),
    "ERR_STUDENT_NOT_FOUND": (404, "Student not found"),
    "ERR_AGREEMENT_NOT_FOUND": (404, "Publisher agreement not found"),
    "ERR_TITLE_NOT_FOUND": (404, "Course material title not found"),
    "ERR_TIER_NOT_FOUND": (404, "Pricing tier not found"),
    "ERR_SECTION_NOT_FOUND": (404, "Course section not found"),
    "ERR_ADOPTION_NOT_FOUND": (404, "Adoption not found"),
    "ERR_ENROLLMENT_NOT_FOUND": (404, "Enrollment not found"),
    "ERR_CHARGE_NOT_FOUND": (404, "Student charge not found"),
    "ERR_LEDGER_ENTRY_NOT_FOUND": (404, "Ledger entry not found"),
    "ERR_OPT_OUT_REQUEST_NOT_FOUND": (404, "Opt-out request not found"),
    "ERR_RUN_NOT_FOUND": (404, "Reconciliation run not found"),
    "ERR_REPORT_NOT_FOUND": (404, "Disclosure report not found"),
    "ERR_INVALID_STATE": (409, "The entity is not in a state that allows this transition"),
    "ERR_TERM_BILLING_LOCKED": (409, "The term's billing is locked; charges and opt-out changes are frozen"),
    "ERR_TERM_NOT_OPEN": (409, "The term is not open for this operation"),
    "ERR_TERM_NOT_LOCKED": (409, "The term's billing must be locked before a reconciliation run can be settled"),
    "ERR_SECTION_NOT_FLAGGED": (409, "The section is not flagged for inclusive access"),
    "ERR_RECONCILIATION_NOT_CURRENT": (409, "A publisher agreement of this term has no current reconciliation"),
    "ERR_DISCLOSURE_DEADLINE_PASSED": (409, "The state disclosure filing deadline has passed"),
    "ERR_AGREEMENT_NOT_ACTIVE": (409, "The publisher agreement pricing this title is not active"),
    "ERR_AGREEMENT_NOT_ACTIVATABLE": (409, "The agreement has no active title, or an active title has no pricing tier"),
    "ERR_ADOPTION_NOT_APPROVED": (409, "The section has no approved adoption"),
    "ERR_ENROLLMENT_NOT_ACTIVE": (409, "The enrollment behind this charge has been dropped"),
    "ERR_TITLE_WITHDRAWN": (409, "The course material title has been withdrawn"),
    "ERR_TITLE_ALREADY_BILLED": (409, "A title adopted by a billed section cannot be withdrawn"),
    "ERR_ADOPTION_DEADLINE_PASSED": (409, "The faculty adoption deadline for this term has passed"),
    "ERR_OPT_OUT_WINDOW_CLOSED": (409, "The opt-out window for this charge has closed"),
    "ERR_LATE_REGISTRATION_CLOSED": (409, "The late registration period for this term has closed"),
    "ERR_TIER_BAND_OVERLAP": (409, "The enrollment band overlaps an existing pricing tier of this title"),
    "ERR_CONCURRENT_TITLE_LIMIT": (409, "Approving this adoption would exceed the section's concurrent title limit"),
    "ERR_DUPLICATE_OPT_OUT_OPEN": (409, "An open opt-out request already exists for this charge"),
    "ERR_OPT_OUT_CYCLE_LIMIT": (409, "This opt-out request has reached its resubmission limit"),
    "ERR_DUPLICATE_ENROLLMENT": (409, "The student is already enrolled in this section"),
    "ERR_DUPLICATE_RESOURCE_KEY": (409, "A resource with this business key already exists"),
    "ERR_CHARGE_ALREADY_EXISTS": (409, "This enrollment already carries a charge on the section's approved adoption"),
    "ERR_VARIANCE_TOLERANCE_EXCEEDED": (409, "The variance against the publisher invoice exceeds the settlement tolerance"),
    "ERR_VARIANCE_WITHIN_TOLERANCE": (409, "The variance against the publisher invoice is within tolerance and cannot be disputed"),
    "ERR_STALE_SECTION_VERSION": (412, "The course section has changed since it was read"),
    "ERR_STALE_AGREEMENT_VERSION": (412, "The publisher agreement has changed since it was read"),
    "ERR_AGREEMENT_WINDOW_MISMATCH": (422, "The agreement's effective window does not cover the term"),
    "ERR_SUPERSEDE_TARGET_INVALID": (422, "The superseded adoption is not an approved adoption of the same section with a different title"),
    "ERR_ENROLLMENT_DATE_OUT_OF_RANGE": (422, "The enrollment or drop date is outside the acceptable range"),
    "ERR_ACCESS_WINDOW_INVALID": (422, "The LMS access window is not a valid half-open interval inside the term"),
    "ERR_NO_PRICING_TIER": (422, "No pricing tier of the adopted title covers this enrollment count"),
    "ERR_NO_BILLABLE_CHARGES": (422, "The section has no uncharged enrolled student to bill"),
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super(ApiError, self).__init__(error_id)
        status, default_message = ERROR_CATALOG.get(error_id, (400, "Request failed"))
        self.error_id = error_id
        self.http_status = http_status or status
        self.message = message or default_message


def fail(error_id, message=None):
    raise ApiError(error_id, message)
