"""Error catalog for the Antimicrobial Stewardship Program API.

Every error_id / HTTP status pair is taken verbatim from PRD section 5
(Error Code Catalogue) and SCAFFOLD.yaml table 6.
"""


class ApiError(Exception):
    """Exception carrying the scaffold-defined error_id and HTTP status."""

    def __init__(self, error_id: str, http_status: int, message: str):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- Auth ---
def err_missing_user_context(msg="X-User-ID or X-User-Role header missing/empty"):
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400, msg)


def err_insufficient_permissions(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403, msg)


# --- Existence / input shape ---
def err_not_found(msg="Path-referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid_request(msg="Missing required field, type mismatch, or enum out of range"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_invalid_period(msg="antibiogram period_end must be after period_start"):
    return ApiError("ERR_INVALID_PERIOD", 422, msg)


def err_invalid_supersession(msg="supersedes_guideline_id is invalid"):
    return ApiError("ERR_INVALID_SUPERSESSION", 422, msg)


# --- State ---
def err_practitioner_inactive(msg="Referenced practitioner is inactive"):
    return ApiError("ERR_PRACTITIONER_INACTIVE", 409, msg)


def err_patient_discharged(msg="Patient case is discharged"):
    return ApiError("ERR_PATIENT_DISCHARGED", 409, msg)


def err_drug_suspended(msg="Antimicrobial formulary_status is SUSPENDED"):
    return ApiError("ERR_DRUG_SUSPENDED", 409, msg)


def err_order_not_auditable(msg="Target order therapy_status is not ACTIVE or REVIEW_REQUIRED"):
    return ApiError("ERR_ORDER_NOT_AUDITABLE", 409, msg)


def err_order_not_iv(msg="Order route is not IV"):
    return ApiError("ERR_ORDER_NOT_IV", 409, msg)


def err_no_oral_form(msg="Antimicrobial has no oral formulation"):
    return ApiError("ERR_NO_ORAL_FORM", 409, msg)


def err_order_approval_not_pending(msg="Order approval_status is not PENDING"):
    return ApiError("ERR_ORDER_APPROVAL_NOT_PENDING", 409, msg)


def err_approval_not_pending(msg="Approval request is not SUBMITTED or ESCALATED"):
    return ApiError("ERR_APPROVAL_NOT_PENDING", 409, msg)


def err_escalated_requires_director(msg="Only StewardshipDirector may decide an ESCALATED request"):
    return ApiError("ERR_ESCALATED_REQUIRES_DIRECTOR", 403, msg)


def err_intervention_not_draft(msg="Intervention is not DOCUMENTED"):
    return ApiError("ERR_INTERVENTION_NOT_DRAFT", 409, msg)


def err_intervention_not_pending(msg="Intervention is not RECOMMENDED"):
    return ApiError("ERR_INTERVENTION_NOT_PENDING", 409, msg)


def err_intervention_not_appealable(msg="Intervention is not REJECTED"):
    return ApiError("ERR_INTERVENTION_NOT_APPEALABLE", 409, msg)


def err_intervention_not_appealed(msg="Intervention is not APPEALED"):
    return ApiError("ERR_INTERVENTION_NOT_APPEALED", 409, msg)


def err_opportunity_not_detected(msg="ConversionOpportunity is not DETECTED"):
    return ApiError("ERR_OPPORTUNITY_NOT_DETECTED", 409, msg)


def err_allergy_not_schedulable(msg="Allergy assessment is not SUSPECTED or CONFIRMED"):
    return ApiError("ERR_ALLERGY_NOT_SCHEDULABLE", 409, msg)


def err_allergy_not_testing(msg="Allergy assessment is not TESTING_SCHEDULED"):
    return ApiError("ERR_ALLERGY_NOT_TESTING", 409, msg)


def err_allergy_terminal(msg="Allergy assessment is in a terminal state"):
    return ApiError("ERR_ALLERGY_TERMINAL", 409, msg)


def err_antibiogram_not_draft(msg="Antibiogram is not DRAFT"):
    return ApiError("ERR_ANTIBIOGRAM_NOT_DRAFT", 409, msg)


def err_antibiogram_empty(msg="Antibiogram has zero reportable rows"):
    return ApiError("ERR_ANTIBIOGRAM_EMPTY", 409, msg)


def err_antibiogram_not_published(msg="Source antibiogram is not PUBLISHED"):
    return ApiError("ERR_ANTIBIOGRAM_NOT_PUBLISHED", 409, msg)


def err_guideline_not_draft(msg="Guideline is not DRAFT"):
    return ApiError("ERR_GUIDELINE_NOT_DRAFT", 409, msg)


def err_guideline_not_stale(msg="Guideline is not STALE"):
    return ApiError("ERR_GUIDELINE_NOT_STALE", 409, msg)


def err_guideline_not_retirable(msg="Guideline is not DRAFT or STALE"):
    return ApiError("ERR_GUIDELINE_NOT_RETIRABLE", 409, msg)


def err_snapshot_not_open(msg="Snapshot is not OPEN"):
    return ApiError("ERR_SNAPSHOT_NOT_OPEN", 409, msg)


def err_snapshot_not_finalized(msg="Snapshot is not FINALIZED"):
    return ApiError("ERR_SNAPSHOT_NOT_FINALIZED", 409, msg)


def err_snapshot_pinned_by_report(msg="Snapshot is pinned by a SUBMITTED or ACCEPTED report"):
    return ApiError("ERR_SNAPSHOT_PINNED_BY_REPORT", 409, msg)


def err_snapshot_not_final(msg="Pinned snapshot must be FINALIZED with matching period and hospital"):
    return ApiError("ERR_SNAPSHOT_NOT_FINAL", 409, msg)


def err_report_not_draft(msg="Report is not DRAFT"):
    return ApiError("ERR_REPORT_NOT_DRAFT", 409, msg)


def err_report_not_submitted(msg="Report is not SUBMITTED"):
    return ApiError("ERR_REPORT_NOT_SUBMITTED", 409, msg)


# --- Business safety ---
def err_allergy_blocks_order(msg="Penicillin-class order blocked by active allergy assessment"):
    return ApiError("ERR_ALLERGY_BLOCKS_ORDER", 422, msg)


def err_renal_dose_exceeded(msg="dose_mg * frequency_per_day exceeds 4000 with CrCl < 30"):
    return ApiError("ERR_RENAL_DOSE_EXCEEDED", 422, msg)


def err_severe_allergy_blocked(msg="SEVERE allergy may never schedule a test"):
    return ApiError("ERR_SEVERE_ALLERGY_BLOCKED", 422, msg)


def err_self_approval_forbidden(msg="Approval decider equals requester"):
    return ApiError("ERR_SELF_APPROVAL_FORBIDDEN", 422, msg)


def err_adjudicator_conflict(msg="Adjudicator equals auditor or original responder"):
    return ApiError("ERR_ADJUDICATOR_CONFLICT", 422, msg)


# --- Business temporal ---
def err_future_specimen(msg="Culture collected_at is after the hospital clock"):
    return ApiError("ERR_FUTURE_SPECIMEN", 422, msg)


def err_intervention_overdue(msg="Response is after due_at"):
    return ApiError("ERR_INTERVENTION_OVERDUE", 422, msg)


def err_antibiogram_window_overlap(msg="Antibiogram window overlaps an existing window"):
    return ApiError("ERR_ANTIBIOGRAM_WINDOW_OVERLAP", 409, msg)


def err_rechallenge_too_early(msg="Rechallenge from CONFIRMED requires years_since_reaction >= 5"):
    return ApiError("ERR_RECHALLENGE_TOO_EARLY", 422, msg)


def err_period_not_closed(msg="Snapshot month is not strictly before the clock month"):
    return ApiError("ERR_PERIOD_NOT_CLOSED", 422, msg)


def err_clock_regression(msg="to_iso8601 must be strictly later than the current clock"):
    return ApiError("ERR_CLOCK_REGRESSION", 422, msg)


# --- Business referential ---
def err_cross_facility(msg="Referenced entity belongs to a different hospital"):
    return ApiError("ERR_CROSS_FACILITY_REFERENCE", 422, msg)


def err_no_supporting_culture(msg="No FINAL culture with S interpretation for the suggested drug"):
    return ApiError("ERR_NO_SUPPORTING_CULTURE", 422, msg)


# --- Business constraint ---
def err_restricted_requires_approval(msg="Restricted drug administration requires APPROVED status"):
    return ApiError("ERR_RESTRICTED_REQUIRES_APPROVAL", 422, msg)


def err_duplicate_active_order(msg="Same patient and antimicrobial with a non-terminal order exists"):
    return ApiError("ERR_DUPLICATE_ACTIVE_ORDER", 409, msg)


def err_restricted_order_cap(msg="Patient already has 2 concurrent restricted orders"):
    return ApiError("ERR_RESTRICTED_ORDER_CAP", 409, msg)


def err_duplicate_row(msg="AntibiogramRow uniqueness per (antibiogram, organism, drug) violated"):
    return ApiError("ERR_DUPLICATE_ROW", 409, msg)


def err_approval_already_open(msg="An open approval request already exists for the order"):
    return ApiError("ERR_APPROVAL_ALREADY_OPEN", 409, msg)


def err_duplicate_snapshot_period(msg="Snapshot for the same hospital and period_label exists"):
    return ApiError("ERR_DUPLICATE_SNAPSHOT_PERIOD", 409, msg)


def err_report_already_submitted(msg="A SUBMITTED/ACCEPTED report already exists for this period"):
    return ApiError("ERR_REPORT_ALREADY_SUBMITTED", 409, msg)


def err_not_request_owner(msg="Withdrawer is not the approval request's requester"):
    return ApiError("ERR_NOT_REQUEST_OWNER", 403, msg)


def err_not_prescriber(msg="Responder is not the order's prescriber"):
    return ApiError("ERR_NOT_PRESCRIBER", 403, msg)


def err_not_audit_owner(msg="Appealer is not the intervention's auditor"):
    return ApiError("ERR_NOT_AUDIT_OWNER", 403, msg)


def err_open_intervention_blocks_close(msg="Order has an intervention in RECOMMENDED or APPEALED"):
    return ApiError("ERR_OPEN_INTERVENTION_BLOCKS_CLOSE", 409, msg)


# --- Business fiscal / threshold ---
def err_first_line_below_threshold(msg="First-line drug susceptibility below 70 or row not reportable"):
    return ApiError("ERR_FIRST_LINE_BELOW_THRESHOLD", 422, msg)


def err_prescriber_suspended(msg="Prescriber stewardship_standing is SUSPENDED"):
    return ApiError("ERR_PRESCRIBER_SUSPENDED", 403, msg)


def err_conversion_not_eligible(msg="IV-to-PO hard gate failed or score below threshold"):
    return ApiError("ERR_CONVERSION_NOT_ELIGIBLE", 422, msg)


def err_deescalation_not_eligible(msg="De-escalation hard gate failed or score below threshold"):
    return ApiError("ERR_DEESCALATION_NOT_ELIGIBLE", 422, msg)


def err_allergy_high_risk(msg="Allergy risk_score >= LOW_RISK_THRESHOLD blocks scheduling"):
    return ApiError("ERR_ALLERGY_HIGH_RISK", 422, msg)


# --- Concurrency ---
def err_stale_version(msg="expected_hospital_version does not match Hospital.version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)
