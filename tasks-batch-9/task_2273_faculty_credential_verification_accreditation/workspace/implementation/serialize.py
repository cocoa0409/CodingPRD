"""Row -> JSON projection. Derived ledgers are recomputed on read."""

import util
from db import store
from services import calc, lookup

# Fields rendered as plain floats so 4dp / 2dp values keep their scale semantics.
_FLOAT_FIELDS = {
    "alignment_score",
    "tested_experience_score",
    "adequacy_ratio",
    "adequacy_ratio_snapshot",
    "preliminary_risk_index",
    "risk_index",
    "min_terminal_ratio",
}


def _project(row, fields):
    out = {"id": row["id"], "created_at": row["created_at"],
           "updated_at": row["updated_at"], "version": row["version"]}
    for name in fields:
        value = row.get(name)
        if name in _FLOAT_FIELDS:
            out[name] = util.fnum(value)
        elif hasattr(value, "quantize"):
            out[name] = util.num(value)
        else:
            out[name] = value
    return out


DISCIPLINE_FIELDS = ("code", "name", "parent_discipline_id",
                     "min_graduate_credit_hours", "required_terminal_degree_level")
PROGRAM_FIELDS = ("name", "discipline_id", "degree_level", "qualification_policy",
                  "adequacy_basis", "min_terminal_ratio", "is_substantive_change",
                  "credential_budget_cents", "budget_reserved_cents",
                  "budget_spent_cents", "launch_status", "adequacy_ratio",
                  "adequacy_status", "unqualified_assignment_count",
                  "adequacy_term_id")
TERM_FIELDS = ("code", "start_date", "end_date", "census_date", "status")
FACULTY_FIELDS = ("full_name", "email", "employment_class", "home_program_id",
                  "dossier_status", "appointment_status", "deficiency_codes",
                  "highest_verified_degree_level", "assigned_credit_hours",
                  "pd_hours_current_cycle", "pd_compliant")
CREDENTIAL_FIELDS = ("faculty_member_id", "degree_level", "discipline_id",
                     "conferring_institution", "is_foreign_institution",
                     "graduate_credit_hours_in_discipline", "transcript_status",
                     "verification_status", "verified_by_user_id",
                     "effective_degree_level", "effective_discipline_id")
EVALUATION_FIELDS = ("credential_record_id", "billed_program_id", "evaluator_agency",
                     "page_count", "service_level", "fee_cents", "status",
                     "equivalency_degree_level", "equivalency_discipline_id",
                     "equivalency_verdict", "allocation_shares")
SECTION_FIELDS = ("course_code", "title", "program_id", "term_id", "discipline_id",
                  "course_level", "credit_hours", "delivery_mode", "building_code",
                  "meeting_days", "meeting_start_minute", "meeting_end_minute",
                  "instructor_of_record_id")
ASSIGNMENT_FIELDS = ("course_section_id", "faculty_member_id", "assignment_role",
                     "status", "qualification_basis", "exception_code",
                     "alignment_score", "remediation_action",
                     "superseded_by_assignment_id")
JUSTIFICATION_FIELDS = ("course_assignment_id", "narrative",
                        "alternative_credential_codes",
                        "documented_years_experience", "industry_certification_level",
                        "supervisor_attestation_on_file", "tested_experience_score",
                        "status", "decided_by_user_id", "decision_rationale")
ROSTER_FIELDS = ("term_id", "program_id", "status", "generation_epoch",
                 "total_assignment_count", "distinct_faculty_count",
                 "flagged_exception_count", "terminal_qualified_headcount",
                 "credit_hours_total", "credit_hours_terminal_qualified",
                 "adequacy_ratio_snapshot", "certification_readiness",
                 "blocking_reason_codes", "certified_at", "certified_by_user_id")
CONTRACT_FIELDS = ("faculty_member_id", "term_id", "employment_class",
                   "contract_credit_hours", "status", "issued_at",
                   "countersigned_at", "dossier_snapshot_status",
                   "credential_snapshot_version")
PD_FIELDS = ("faculty_member_id", "discipline_id", "activity_type", "contact_hours",
             "activity_date", "status", "discipline_relevant")
REVIEW_FIELDS = ("program_id", "review_type", "window_start_date", "window_end_date",
                 "status", "finding_count", "unqualified_assignment_ids",
                 "preliminary_risk_index", "risk_tier", "risk_index",
                 "response_due_date", "response_round", "response_narrative")


def discipline(row):
    return _project(row, DISCIPLINE_FIELDS)


def program(row):
    reserved = 0
    spent = 0
    for ev in store.credential_evaluations.values():
        if ev["status"] in ("ORDERED", "IN_REVIEW") and ev["billed_program_id"] == row["id"]:
            reserved += int(ev["fee_cents"])
        if ev["status"] == "COMPLETED":
            for share in ev.get("allocation_shares") or []:
                if share["program_id"] == row["id"]:
                    spent += int(share["share_cents"])
    row["budget_reserved_cents"] = reserved
    row["budget_spent_cents"] = spent
    return _project(row, PROGRAM_FIELDS)


def term(row):
    return _project(row, TERM_FIELDS)


def faculty(row):
    row["assigned_credit_hours"] = calc.assigned_credit_hours(row["id"])
    result = calc.pd_compliance(row)
    row["pd_hours_current_cycle"] = result["pd_hours_current_cycle"]
    row["pd_compliant"] = result["pd_compliant"]
    return _project(row, FACULTY_FIELDS)


def credential(row):
    return _project(row, CREDENTIAL_FIELDS)


def evaluation(row):
    out = _project(row, EVALUATION_FIELDS)
    out["allocation_shares"] = [
        {"program_id": s["program_id"],
         "weight_credit_hours": util.num(s["weight_credit_hours"]),
         "share_cents": int(s["share_cents"])}
        for s in (row.get("allocation_shares") or [])
    ]
    return out


def section(row):
    return _project(row, SECTION_FIELDS)


def assignment(row):
    return _project(row, ASSIGNMENT_FIELDS)


def justification(row):
    return _project(row, JUSTIFICATION_FIELDS)


def roster(row):
    return _project(row, ROSTER_FIELDS)


def contract(row):
    return _project(row, CONTRACT_FIELDS)


def pd_record(row):
    return _project(row, PD_FIELDS)


def review(row):
    return _project(row, REVIEW_FIELDS)
