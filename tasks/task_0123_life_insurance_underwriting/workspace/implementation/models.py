"""Record construction, common-field stamping, and serialization.

Common fields (PRD §2.4):
  - Full quartet (id, created_at, updated_at, version): Product, Applicant,
    Underwriter, Application, ParamedExam, RiskAssessment, Policy, Beneficiary,
    PolicyLoan.
  - id + created_at only (append-only / non-versioned): MIBCheck,
    CashValueEntry, PremiumPayment.
"""
from db import new_id, now_iso, store

# Entities that carry only id + created_at (no updated_at, no version).
_AUDIT_ONLY = {"MIBCheck", "CashValueEntry", "PremiumPayment"}


def make_record(entity_type, fields):
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = now_iso()
    rec["_seq"] = store.next_seq()
    rec["_type"] = entity_type
    if entity_type not in _AUDIT_ONLY:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Mark a versioned record as mutated: bump version, refresh updated_at."""
    if rec.get("_type") not in _AUDIT_ONLY:
        rec["version"] = rec.get("version", 1) + 1
        rec["updated_at"] = now_iso()


# Field projection per entity for serialization (output shape). Internal fields
# (those prefixed with `_`) are stripped.

_COMMON_QUARTET = ["id", "created_at", "updated_at", "version"]
_COMMON_AUDIT = ["id", "created_at"]

_ENTITY_FIELDS = {
    "Product": ["code", "base_annual_rate_per_thousand_cents", "max_face_amount_cents",
                "cash_value_accrual_rate_bps", "contestability_months", "grace_period_days",
                "max_loan_to_cash_value_pct", "exam_validity_days"],
    "Applicant": ["full_name", "date_of_birth", "sex", "tobacco_use", "email"],
    "Underwriter": ["name", "license_id"],
    "Application": ["applicant_id", "product_id", "ordering_underwriter_id",
                    "deciding_underwriter_id", "requested_face_amount_cents", "status",
                    "offer_expires_at", "provisional_annual_premium_cents",
                    "final_annual_premium_cents"],
    "ParamedExam": ["application_id", "height_inches", "weight_pounds", "systolic_bp",
                    "exam_date", "status"],
    "MIBCheck": ["application_id", "mib_hit", "rx_flag_count", "result"],
    "RiskAssessment": ["application_id", "build_debits", "total_debits", "risk_class",
                       "table_rating", "finalized"],
    "Policy": ["application_id", "face_amount_cents", "annual_premium_cents", "issue_date",
               "lifecycle_status", "contestability_status", "next_premium_due_date",
               "cumulative_premium_paid_cents", "gross_cash_value_cents",
               "outstanding_loan_principal_cents", "net_cash_value_cents"],
    "Beneficiary": ["policy_id", "full_name", "designation", "share_pct"],
    "PremiumPayment": ["policy_id", "amount_cents", "paid_at", "applied_to_due_date",
                       "coverage_period_start", "coverage_period_end"],
    "PolicyLoan": ["policy_id", "principal_cents", "status"],
    "CashValueEntry": ["policy_id", "amount_cents", "reason"],
}


def serialize(rec):
    entity_type = rec["_type"]
    base = _COMMON_AUDIT if entity_type in _AUDIT_ONLY else _COMMON_QUARTET
    out = {}
    for f in base:
        out[f] = rec.get(f)
    for f in _ENTITY_FIELDS[entity_type]:
        out[f] = rec.get(f)
    return out
