"""Error classes carrying scaffold error_id + http_status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- Auth ---
def err_missing_context():
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                    "X-User-Role or X-User-ID header missing, or role not recognized")


def err_forbidden_role():
    return ApiError("ERR_FORBIDDEN_ROLE", 403,
                    "Authenticated role is not permitted on this endpoint")


def err_not_owner():
    return ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                    "Caller does not own the targeted resource")


# --- Existence ---
def err_fund_not_found():
    return ApiError("ERR_FUND_NOT_FOUND", 404, "Trust fund id does not exist")


def err_employer_not_found():
    return ApiError("ERR_EMPLOYER_NOT_FOUND", 404, "Employer id does not exist")


def err_apprentice_not_found():
    return ApiError("ERR_APPRENTICE_NOT_FOUND", 404, "Apprentice id does not exist")


def err_report_not_found():
    return ApiError("ERR_REPORT_NOT_FOUND", 404, "Contribution report id does not exist")


def err_class_not_found():
    return ApiError("ERR_CLASS_NOT_FOUND", 404, "Training class id does not exist")


def err_enrollment_not_found():
    return ApiError("ERR_ENROLLMENT_NOT_FOUND", 404, "Enrollment id does not exist")


def err_claim_not_found():
    return ApiError("ERR_CLAIM_NOT_FOUND", 404, "Pay claim id does not exist")


def err_allocation_not_found():
    return ApiError("ERR_ALLOCATION_NOT_FOUND", 404, "Funding allocation id does not exist")


def err_purchase_not_found():
    return ApiError("ERR_PURCHASE_NOT_FOUND", 404, "Equipment purchase id does not exist")


# --- Shape ---
def err_invalid_request(msg="Missing required field, wrong type, empty lines array, or missing actual_minutes"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_invalid_period():
    return ApiError("ERR_INVALID_PERIOD", 400,
                    "period_month outside 1..12, or the period has not started yet")


def err_invalid_class_window():
    return ApiError("ERR_INVALID_CLASS_WINDOW", 400, "end_minute must be strictly greater than start_minute")


def err_invalid_registration_outcome():
    return ApiError("ERR_INVALID_REGISTRATION_OUTCOME", 400,
                    "outcome must be one of REGISTERED, REJECTED, REVOKED")


# --- State ---
def err_invalid_state(msg="Invalid state for the requested transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_apprentice_not_indentured():
    return ApiError("ERR_APPRENTICE_NOT_INDENTURED", 409,
                    "Enrollment requires the apprentice's program_status to be INDENTURED")


def err_registration_required():
    return ApiError("ERR_REGISTRATION_REQUIRED", 409,
                    "Operation requires registration_status == REGISTERED")


def err_registration_not_submitted():
    return ApiError("ERR_REGISTRATION_NOT_SUBMITTED", 409,
                    "record-registration-decision requires registration_status == SUBMITTED")


def err_report_not_flaggable():
    return ApiError("ERR_REPORT_NOT_FLAGGABLE", 409, "flag requires the report to be SUBMITTED")


def err_report_not_resubmittable():
    return ApiError("ERR_REPORT_NOT_RESUBMITTABLE", 409, "resubmit requires the report to be FLAGGED")


def err_report_not_payable():
    return ApiError("ERR_REPORT_NOT_PAYABLE", 409,
                    "remit requires the report to be SUBMITTED or DELINQUENT")


def err_class_not_scheduled():
    return ApiError("ERR_CLASS_NOT_SCHEDULED", 409, "Operation requires the class to be SCHEDULED")


def err_enrollment_not_open():
    return ApiError("ERR_ENROLLMENT_NOT_OPEN", 409, "drop requires the enrollment to be ENROLLED")


def err_claim_not_approvable():
    return ApiError("ERR_CLAIM_NOT_APPROVABLE", 409, "approve or reject requires the claim to be SUBMITTED")


def err_claim_not_payable():
    return ApiError("ERR_CLAIM_NOT_PAYABLE", 409, "pay requires the claim to be APPROVED")


def err_allocation_not_activable():
    return ApiError("ERR_ALLOCATION_NOT_ACTIVABLE", 409,
                    "approve or reject requires the allocation to be PROPOSED")


def err_allocation_not_active():
    return ApiError("ERR_ALLOCATION_NOT_ACTIVE", 409,
                    "purchase creation requires an ACTIVE allocation")


def err_purchase_not_requested():
    return ApiError("ERR_PURCHASE_NOT_REQUESTED", 409,
                    "approve or deny requires the purchase to be REQUESTED")


def err_purchase_not_approved():
    return ApiError("ERR_PURCHASE_NOT_APPROVED", 409,
                    "mark-purchased requires the purchase to be APPROVED")


def err_stale_version():
    return ApiError("ERR_STALE_VERSION", 412,
                    "expected_trust_fund_version does not match the fund's current version")


# --- Compliance / safety ---
def err_fund_on_compliance_hold():
    return ApiError("ERR_FUND_ON_COMPLIANCE_HOLD", 409,
                    "Fund posture is COMPLIANCE_HOLD; new financial commitments are blocked")


def err_self_approval():
    return ApiError("ERR_SELF_APPROVAL_FORBIDDEN", 403,
                    "Segregation of duties: approver must differ from proposer/requester")


def err_certification_not_met():
    return ApiError("ERR_CERTIFICATION_REQUIREMENTS_NOT_MET", 409,
                    "Certification requires 8000 OJT hours, 576 RTI credits, and REGISTERED registration")


# --- Uniqueness / capacity / scheduling ---
def err_duplicate_report_period():
    return ApiError("ERR_DUPLICATE_REPORT_PERIOD", 409,
                    "A report already exists for this employer and period")


def err_duplicate_enrollment():
    return ApiError("ERR_DUPLICATE_ENROLLMENT", 409,
                    "An ENROLLED enrollment already exists for this apprentice in this class")


def err_duplicate_claim():
    return ApiError("ERR_DUPLICATE_CLAIM", 409,
                    "A pay claim for this class already exists in SUBMITTED or APPROVED status")


def err_class_full():
    return ApiError("ERR_CLASS_FULL", 409, "The class is at capacity")


def err_instructor_conflict():
    return ApiError("ERR_INSTRUCTOR_SCHEDULE_CONFLICT", 409,
                    "Same instructor has a SCHEDULED class within the 30-minute turnover buffer")


def err_facility_conflict():
    return ApiError("ERR_FACILITY_SCHEDULE_CONFLICT", 409,
                    "Same facility has an overlapping SCHEDULED class")


def err_invalid_attendee_list():
    return ApiError("ERR_INVALID_ATTENDEE_LIST", 400,
                    "attended_enrollment_ids references an unknown, foreign, or non-ENROLLED enrollment")


def err_overtime_cap():
    return ApiError("ERR_OVERTIME_CAP_EXCEEDED", 422,
                    "actual_minutes exceeds the overtime cap")


def err_apprentice_not_hour_eligible():
    return ApiError("ERR_APPRENTICE_NOT_HOUR_ELIGIBLE", 400,
                    "A report line's apprentice is not in program_status INDENTURED or SUSPENDED")


def err_line_employer_mismatch():
    return ApiError("ERR_LINE_EMPLOYER_MISMATCH", 400,
                    "A report line's apprentice belongs to a different employer than the report")


# --- Fiscal ---
def err_remittance_mismatch():
    return ApiError("ERR_REMITTANCE_AMOUNT_MISMATCH", 400,
                    "amount_tendered_cents must equal contribution_due_cents exactly")


def err_insufficient_fund():
    return ApiError("ERR_INSUFFICIENT_FUND_AVAILABLE", 402,
                    "Allocation amount exceeds the fund's available_cents")


def err_insufficient_allocation():
    return ApiError("ERR_INSUFFICIENT_ALLOCATION_REMAINING", 402,
                    "Purchase amount exceeds the allocation's remaining_cents")
