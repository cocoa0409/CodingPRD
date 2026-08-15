"""Error classes and error ID constants from the scaffold error catalog."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(msg="Missing or invalid X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_unauthorized_role(msg="Role not authorized for this endpoint"):
    return ApiError("ERR_UNAUTHORIZED_ROLE", 403, msg)


def err_not_resource_owner(msg="ProducerRep does not own the target resource"):
    return ApiError("ERR_NOT_RESOURCE_OWNER", 403, msg)


def err_validation(msg="Malformed body, missing field, undeclared enum member, or out-of-range value"):
    return ApiError("ERR_VALIDATION", 400, msg)


def err_not_found(msg="Referenced resource does not exist"):
    return ApiError("ERR_RESOURCE_NOT_FOUND", 404, msg)


def err_stale_version(msg="Expected version does not match the entity's current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def err_application_state(msg="Application not in the required from-state"):
    return ApiError("ERR_APPLICATION_STATE", 409, msg)


def err_production_state(msg="Production status does not permit the operation"):
    return ApiError("ERR_PRODUCTION_STATE", 409, msg)


def err_posture_frozen(msg="Operation blocked while compliance posture is FROZEN"):
    return ApiError("ERR_POSTURE_FROZEN", 409, msg)


def err_posture_restricted(msg="Operation requires CLEAR compliance posture but posture is RESTRICTED"):
    return ApiError("ERR_POSTURE_RESTRICTED", 409, msg)


def err_bond_state(msg="Bond not in the required from-state"):
    return ApiError("ERR_BOND_STATE", 409, msg)


def err_assignment_state(msg="Crew assignment not in the required from-state"):
    return ApiError("ERR_ASSIGNMENT_STATE", 409, msg)


def err_worklog_state(msg="Work log not in the required from-state"):
    return ApiError("ERR_WORKLOG_STATE", 409, msg)


def err_grievance_state(msg="Grievance not in the required from-state"):
    return ApiError("ERR_GRIEVANCE_STATE", 409, msg)


def err_report_state(msg="Contribution report not in the required from-state"):
    return ApiError("ERR_REPORT_STATE", 409, msg)


def err_audit_state(msg="Audit not in the required from-state"):
    return ApiError("ERR_AUDIT_STATE", 409, msg)


def err_fm_state(msg="Force majeure event not ACTIVE"):
    return ApiError("ERR_FM_STATE", 409, msg)


def err_company_not_signatory(msg="Production creation requires the company status == SIGNATORY"):
    return ApiError("ERR_COMPANY_NOT_SIGNATORY", 409, msg)


def err_min_staff_unmet(msg="Per-tier per-department minimum staffing not satisfied"):
    return ApiError("ERR_MIN_STAFF_UNMET", 422, msg)


def err_filing_window_expired(msg="Grievance filed after the filing deadline"):
    return ApiError("ERR_FILING_WINDOW_EXPIRED", 422, msg)


def err_cross_production_reference(msg="Referenced resource belongs to a different production"):
    return ApiError("ERR_CROSS_PRODUCTION_REFERENCE", 422, msg)


def err_log_already_reported(msg="A listed work day log already appears on another ACCEPTED report"):
    return ApiError("ERR_LOG_ALREADY_REPORTED", 409, msg)


def err_duplicate_active_assignment(msg="Another live assignment exists for the same crew member on this production"):
    return ApiError("ERR_DUPLICATE_ACTIVE_ASSIGNMENT", 409, msg)


def err_duplicate_work_log(msg="A non-VOIDED work day log already exists for this assignment and date"):
    return ApiError("ERR_DUPLICATE_WORK_LOG", 409, msg)


def err_duplicate_report_period(msg="A live report already exists for this production and period"):
    return ApiError("ERR_DUPLICATE_REPORT_PERIOD", 409, msg)


def err_fm_overlap(msg="Force majeure interval overlaps an existing event of the production"):
    return ApiError("ERR_FM_OVERLAP", 409, msg)


def err_segregation_of_duties(msg="Same operator attempted both steps of a segregated pair"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


def err_review_rounds_exhausted(msg="Application review rounds exhausted (max 3)"):
    return ApiError("ERR_REVIEW_ROUNDS_EXHAUSTED", 422, msg)


def err_empty_report(msg="Contribution report requires a non-empty work_day_log_ids set"):
    return ApiError("ERR_EMPTY_REPORT", 422, msg)


def err_invalid_worklog_times(msg="Invalid work log times"):
    return ApiError("ERR_INVALID_WORKLOG_TIMES", 422, msg)


def err_tier_cap_exceeded(msg="Budget exceeds the selected agreement tier's cap"):
    return ApiError("ERR_TIER_CAP_EXCEEDED", 422, msg)


def err_bond_amount_insufficient(msg="Bond amount below requirement"):
    return ApiError("ERR_BOND_AMOUNT_INSUFFICIENT", 422, msg)


def err_overpayment(msg="Payment would exceed the outstanding obligation, or amount not positive"):
    return ApiError("ERR_OVERPAYMENT", 422, msg)


def err_refund_exceeds_paid(msg="Refund exceeds amount paid, or amount not positive"):
    return ApiError("ERR_REFUND_EXCEEDS_PAID", 422, msg)
