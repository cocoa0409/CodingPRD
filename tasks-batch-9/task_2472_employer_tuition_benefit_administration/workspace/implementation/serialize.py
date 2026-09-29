"""Resource representations.  Field order follows the entity declarations; the
derived fields (employer roll-ups, employee_share_cents) are computed on read."""

import domain

COMMON_TAIL = ("created_at", "updated_at", "version")
APPEND_ONLY_TAIL = ("created_at",)

EMPLOYER_FIELDS = (
    "id",
    "legal_name",
    "benefit_admin_contact_email",
    "fiscal_year_start_month",
    "status",
    "total_disbursed_cents",
    "total_admin_fee_cents",
    "total_imputed_income_cents",
) + COMMON_TAIL

POLICY_FIELDS = (
    "id",
    "employer_id",
    "effective_from",
    "effective_to",
    "status",
    "min_tenure_months",
    "min_weekly_hours",
    "eligible_job_families",
    "annual_cap_cents",
    "funding_model",
    "reimbursement_pct",
    "max_concurrent_credits",
    "drop_window_days",
    "service_commitment_months",
    "min_passing_grade_points",
    "non_catalog_approval_required",
) + COMMON_TAIL

EMPLOYEE_FIELDS = (
    "id",
    "employer_id",
    "full_name",
    "work_email",
    "hire_date",
    "weekly_hours",
    "job_family",
    "employment_status",
    "termination_date",
    "tenure_months",
    "eligibility_status",
    "cap_plan_year",
    "cap_reserved_cents",
    "cap_disbursed_cents",
    "cap_clawback_hold_cents",
    "cap_available_cents",
    "taxable_excluded_cents_ytd",
    "imputed_income_cents_ytd",
    "open_repayment_balance_cents",
    "coaching_hold",
) + COMMON_TAIL

SCHOOL_FIELDS = (
    "id",
    "legal_name",
    "state_code",
    "contact_email",
    "accreditation_status",
) + COMMON_TAIL

AGREEMENT_FIELDS = (
    "id",
    "school_id",
    "employer_id",
    "negotiated_discount_pct",
    "direct_bill_enabled",
    "effective_from",
    "effective_to",
    "status",
    "terminated_on",
) + COMMON_TAIL

PROGRAM_FIELDS = (
    "id",
    "school_id",
    "name",
    "credential_type",
    "skill_track",
    "list_tuition_per_credit_cents",
    "total_credits",
    "term_length_weeks",
) + COMMON_TAIL

LISTING_FIELDS = (
    "id",
    "employer_id",
    "program_id",
    "agreement_id",
    "source_request_id",
    "approval_source",
    "status",
    "negotiated_tuition_per_credit_cents",
    "allowed_funding_models",
) + COMMON_TAIL

REQUEST_FIELDS = (
    "id",
    "employee_id",
    "program_id",
    "justification",
    "requested_annual_cost_cents",
    "status",
    "revision_count",
    "decision_note",
) + COMMON_TAIL

ENROLLMENT_FIELDS = (
    "id",
    "employee_id",
    "catalog_listing_id",
    "policy_id",
    "term_code",
    "term_start_date",
    "term_end_date",
    "credits",
    "funding_model",
    "plan_year",
    "drop_deadline_date",
    "gross_tuition_cents",
    "employer_reserved_cents",
    "employer_settled_cents",
    "employer_disbursed_cents",
    "employee_share_cents",
    "academic_status",
    "funding_status",
    "credits_earned",
    "persistence_risk_score",
    "persistence_tier",
    "last_session_date",
) + COMMON_TAIL

INVOICE_FIELDS = (
    "id",
    "enrollment_id",
    "amount_cents",
    "due_date",
    "status",
    "paid_on",
) + COMMON_TAIL

CLAIM_FIELDS = (
    "id",
    "enrollment_id",
    "amount_requested_cents",
    "receipt_reference",
    "status",
    "approved_amount_cents",
    "platform_admin_fee_cents",
    "decision_note",
) + COMMON_TAIL

OUTCOME_FIELDS = (
    "id",
    "enrollment_id",
    "term_code",
    "completion_status",
    "grade_points",
    "credits_earned",
    "posted_on",
    "posted_by_role",
) + APPEND_ONLY_TAIL

OBLIGATION_FIELDS = (
    "id",
    "enrollment_id",
    "trigger_reason",
    "principal_cents",
    "paid_cents",
    "waived_cents",
    "balance_cents",
    "status",
    "assessed_on",
) + COMMON_TAIL

TAX_ENTRY_FIELDS = (
    "id",
    "employee_id",
    "enrollment_id",
    "entry_type",
    "tax_year",
    "benefit_cents",
    "excluded_cents",
    "imputed_income_cents",
    "posted_at",
) + APPEND_ONLY_TAIL

SESSION_FIELDS = (
    "id",
    "enrollment_id",
    "coach_user_id",
    "session_date",
    "modality",
    "risk_flags",
    "notes",
    "persistence_risk_score_after",
) + APPEND_ONLY_TAIL


def _project(row, fields):
    return {field: row.get(field) for field in fields}


def employer(row):
    out = _project(row, EMPLOYER_FIELDS)
    out["total_disbursed_cents"] = domain.employer_total_disbursed(row["id"])
    out["total_admin_fee_cents"] = domain.employer_total_admin_fee(row["id"])
    out["total_imputed_income_cents"] = domain.employer_total_imputed_income(row["id"])
    return out


def policy(row):
    return _project(row, POLICY_FIELDS)


def employee(row):
    return _project(row, EMPLOYEE_FIELDS)


def school(row):
    return _project(row, SCHOOL_FIELDS)


def agreement(row):
    return _project(row, AGREEMENT_FIELDS)


def program(row):
    return _project(row, PROGRAM_FIELDS)


def listing(row):
    return _project(row, LISTING_FIELDS)


def request(row):
    return _project(row, REQUEST_FIELDS)


def enrollment(row):
    out = _project(row, ENROLLMENT_FIELDS)
    funding = row["funding_status"]
    if funding in ("SETTLED", "CLAWED_BACK"):
        out["employee_share_cents"] = row["gross_tuition_cents"] - row["employer_settled_cents"]
    elif funding == "RELEASED":
        out["employee_share_cents"] = row["gross_tuition_cents"]
    else:
        out["employee_share_cents"] = row["gross_tuition_cents"] - row["employer_reserved_cents"]
    return out


def invoice(row):
    return _project(row, INVOICE_FIELDS)


def claim(row):
    return _project(row, CLAIM_FIELDS)


def outcome(row):
    return _project(row, OUTCOME_FIELDS)


def obligation(row):
    return _project(row, OBLIGATION_FIELDS)


def tax_entry(row):
    return _project(row, TAX_ENTRY_FIELDS)


def session(row):
    return _project(row, SESSION_FIELDS)


def many(rows, fn):
    return [fn(row) for row in rows]
