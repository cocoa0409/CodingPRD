"""Resource field projections plus shared fetch/list helpers."""
import db
from errors import ApiError
from response import ok_list, serialize
from validate import pagination

COMMON = ("created_at", "updated_at", "version")

ENGINEER = ("id", "full_name", "email", "home_jurisdiction", "ncees_record_id",
            "active_license_number", "open_case_count") + COMMON

LICENSE = ("id", "engineer_id", "license_number", "license_type", "status",
           "issued_on", "current_period_start", "current_period_end",
           "renewal_window_opens_at", "pdh_requirement",
           "reinstatement_eligible_until", "suspension_ends_at",
           "discipline_flag") + COMMON

APPLICATION = ("id", "engineer_id", "pathway", "exam_code", "expedite_requested",
               "status", "education_status", "degree_level",
               "provisional_experience_months", "verified_experience_months",
               "credit_determined_by_user_id", "reviewer_user_id",
               "deficiency_cycle_count", "deficiency_reason", "deficiency_due_at",
               "fee_assessment_cents", "fee_paid_cents", "submitted_at",
               "ncees_record_status", "ncees_verified_exam_pass",
               "ncees_verified_years_licensed", "ncees_disciplinary_history_count",
               "ncees_record_expires_on", "denial_reason") + COMMON

EXPERIENCE_RECORD = ("id", "application_id", "employer_name", "position_title",
                     "period_start_month", "period_end_month",
                     "responsibility_level", "post_degree", "raw_months",
                     "credit_multiplier", "credited_months",
                     "verification_status") + COMMON

REFERENCE = ("id", "experience_record_id", "referee_engineer_id", "relationship",
             "status", "evaluation_score", "months_confirmed",
             "responsibility_confirmed", "submitted_at", "recant_reason") + COMMON

TEST_CENTER = ("id", "name", "state_code", "seat_labels", "seat_count",
               "seats_committed", "seats_available", "status") + COMMON

EXAM_AUTHORIZATION = ("id", "application_id", "exam_code", "status",
                      "authorization_expires_at", "attempt_number", "raw_score",
                      "result", "retake_eligible_at",
                      "ncees_transmission_id") + COMMON

EXAM_APPOINTMENT = ("id", "exam_authorization_id", "test_center_id", "seat_label",
                    "window_start", "window_end", "status") + COMMON

FIRM_REGISTRATION = ("id", "firm_name", "state_code", "responsible_charge_license_id",
                     "status", "registration_expires_at", "lapsed_at") + COMMON

PLAN_SUBMISSION = ("id", "firm_registration_id", "project_name", "sheet_count",
                   "sealing_license_id", "responsible_charge_attested",
                   "seal_affixed_at", "status") + COMMON

CPC_AUDIT = ("id", "audit_cycle_label", "sample_pct", "as_of_period_end",
             "pool_size", "sampled_count", "created_by_user_id", "status") + COMMON

CPC_REPORT = ("id", "license_id", "period_start", "period_end",
              "self_certified_pdh", "carryover_pdh_claimed",
              "self_certified_total_pdh", "audit_verified_total_pdh",
              "shortfall_pdh", "audit_id", "supersedes_report_id",
              "audit_decided_by_user_id", "status") + COMMON

PDH_RECORD = ("id", "cpc_report_id", "activity_type", "pdh_hours", "completed_on",
              "ethics_flag", "documentation_status", "created_at")

CASE = ("id", "allegation_type", "respondent_license_id",
        "subject_plan_submission_id", "unlicensed_respondent_name",
        "complainant_name", "received_on", "investigation_status",
        "sanction_status", "assigned_investigator_user_id",
        "aggravating_factor_count", "mitigating_factor_count", "violation_count",
        "penalty_factor", "assessed_penalty_cents") + COMMON

CONSENT_ORDER = ("id", "case_id", "sanction_type", "suspension_months",
                 "penalty_cents", "penalty_paid_cents", "executed_on",
                 "executed_by_user_id", "status") + COMMON


def fetch(collection, row_id, error_id):
    row = db.get(collection, row_id)
    if row is None:
        raise ApiError(error_id, "%s not found" % collection[:-1])
    return row


def view(row, fields):
    return serialize(row, fields)


def listing(collection, fields, predicate=None, rows=None):
    if rows is None:
        rows = db.all_rows(collection)
    if predicate is not None:
        rows = [r for r in rows if predicate(r)]
    limit, offset = pagination()
    total = len(rows)
    window = rows[offset:offset + limit]
    return ok_list([serialize(r, fields) for r in window], limit, offset, total)
