"""Error classes and error ID constants per the scaffold error catalog."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_unauthenticated(msg="Missing or invalid X-User-Role or X-User-ID header"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_forbidden(msg="Role not allowed on endpoint, or ownership mismatch"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def err_not_found(msg="Path id does not exist"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_validation(msg="Malformed body"):
    return ApiError("ERR_VALIDATION", msg, 400)


def err_invalid_state(msg="Requested transition is not defined from the entity's current state"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_stale_version(msg="Expected version does not match current version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def err_applicant_barred(msg="Applicant is BARRED"):
    return ApiError("ERR_APPLICANT_BARRED", msg, 409)


def err_moral_attestation(msg="moral_character_attestation is not true"):
    return ApiError("ERR_MORAL_ATTESTATION_REQUIRED", msg, 409)


def err_open_misconduct(msg="License has an open misconduct case"):
    return ApiError("ERR_OPEN_MISCONDUCT_CASE", msg, 409)


def err_background_hold(msg="A background check of the applicant is FLAGGED or in ADJUDICATION"):
    return ApiError("ERR_BACKGROUND_HOLD", msg, 409)


def err_duplicate_open_application(msg="A non-terminal application already exists for (applicant, subject_area)"):
    return ApiError("ERR_DUPLICATE_OPEN_APPLICATION", msg, 409)


def err_endorsement_duplicate(msg="License already has this subject_area"):
    return ApiError("ERR_ENDORSEMENT_DUPLICATE", msg, 409)


def err_permit_interval_overlap(msg="Permit interval overlaps an existing permit"):
    return ApiError("ERR_PERMIT_INTERVAL_OVERLAP", msg, 409)


def err_suspension_interval_overlap(msg="Suspension interval overlaps an existing suspension"):
    return ApiError("ERR_SUSPENSION_INTERVAL_OVERLAP", msg, 409)


def err_audit_already_open(msg="A CE audit is already open for the license"):
    return ApiError("ERR_AUDIT_ALREADY_OPEN", msg, 409)


def err_background_check_open(msg="A non-terminal background check already exists for the application"):
    return ApiError("ERR_BACKGROUND_CHECK_OPEN", msg, 409)


def err_segregation_of_duties(msg="Adjudicating user id equals the case's investigator_user_id"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", msg, 409)


def err_pathway_program_required(msg="pathway=TRADITIONAL without program_id, or program_id supplied for a non-TRADITIONAL pathway"):
    return ApiError("ERR_PATHWAY_PROGRAM_REQUIRED", msg, 409)


def err_program_not_approved(msg="Program is not APPROVED or does not cover the application's subject_area"):
    return ApiError("ERR_PROGRAM_NOT_APPROVED", msg, 409)


def err_reciprocity_not_finalized(msg="RECIPROCITY application lacks a finalized non-DENIED evaluation"):
    return ApiError("ERR_RECIPROCITY_NOT_FINALIZED", msg, 409)


def err_renewal_window_closed(msg="Clock now is outside the renewal window"):
    return ApiError("ERR_RENEWAL_WINDOW_CLOSED", msg, 409)


def err_reinstate_grace_expired(msg="Clock now is after expires_on + 730 days"):
    return ApiError("ERR_REINSTATE_GRACE_EXPIRED", msg, 409)


def err_permit_duration_exceeded(msg="valid_until - valid_from exceeds 365 days"):
    return ApiError("ERR_PERMIT_DURATION_EXCEEDED", msg, 409)


def err_plan_deadline_passed(msg="Plan extension already used"):
    return ApiError("ERR_PLAN_DEADLINE_PASSED", msg, 409)


def err_fee_unpaid(msg="fee_status is not PAID"):
    return ApiError("ERR_FEE_UNPAID", msg, 402)


def err_fee_already_paid(msg="fee_status is already PAID"):
    return ApiError("ERR_FEE_ALREADY_PAID", msg, 409)


def err_fee_amount_mismatch(msg="pays_amount_cents does not equal computed reinstatement fee"):
    return ApiError("ERR_FEE_AMOUNT_MISMATCH", msg, 409)


def err_deficiency_outstanding(msg="Deficiency hours outstanding or no COMPLETED plan"):
    return ApiError("ERR_DEFICIENCY_OUTSTANDING", msg, 409)


def err_deficiency_not_present(msg="No deficiency exists"):
    return ApiError("ERR_DEFICIENCY_NOT_PRESENT", msg, 409)


def err_transcripts_unverified(msg="No transcript exists, or some transcript is not VERIFIED"):
    return ApiError("ERR_TRANSCRIPTS_UNVERIFIED", msg, 409)


def err_exam_requirement_unmet(msg="A required exam lacks a VERIFIED passing TestScore"):
    return ApiError("ERR_EXAM_REQUIREMENT_UNMET", msg, 409)


def err_background_not_cleared(msg="Background check missing, DENIED, or not CLEARED"):
    return ApiError("ERR_BACKGROUND_NOT_CLEARED", msg, 409)


def err_audit_not_passed(msg="Required PASSED audit not found"):
    return ApiError("ERR_AUDIT_NOT_PASSED", msg, 409)


def err_audit_hours_insufficient(msg="verified_hours below required_hours"):
    return ApiError("ERR_AUDIT_HOURS_INSUFFICIENT", msg, 409)


def err_case_finding_required(msg="finding is required for adjudication"):
    return ApiError("ERR_CASE_FINDING_REQUIRED", msg, 409)
