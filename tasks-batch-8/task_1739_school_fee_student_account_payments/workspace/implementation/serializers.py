"""Entity serializers: whitelist public fields in scaffold-declared order.
Internal bookkeeping fields are prefixed with '_' and never serialized."""
from core import (db, pub, assessment_outstanding, family_balance, case_bucket)

YEAR_FIELDS = (
    "id", "label", "start_date", "end_date", "refund_full_days",
    "refund_partial_days", "partial_refund_pct_bp", "payment_plan_min_cents",
    "payment_plan_max_installments", "writeoff_max_cents", "aging_interval_days",
    "graduation_hold_threshold_cents", "status", "created_at", "updated_at",
    "version",
)

STUDENT_FIELDS = (
    "id", "external_ref", "full_name", "grade_level", "family_id", "status",
    "created_at", "updated_at", "version",
)

DEPARTMENT_FIELDS = (
    "id", "school_year_id", "code", "name", "created_at", "updated_at",
    "version",
)

OFFERING_FIELDS = (
    "id", "school_year_id", "kind", "title", "department_id", "fee_item_id",
    "start_date", "end_date", "capacity", "status", "created_at", "updated_at",
    "version",
)

FEE_ITEM_FIELDS = (
    "id", "school_year_id", "name", "amount_cents", "department_id",
    "waiverable", "refundable", "status", "created_at", "updated_at", "version",
)

PURCHASE_ITEM_FIELDS = (
    "id", "school_year_id", "name", "amount_cents", "department_id",
    "refundable", "inventory_cap", "sold_count", "created_at", "updated_at",
    "version",
)

ENROLLMENT_FIELDS = (
    "id", "student_account_id", "offering_id", "enrolled_at", "withdrawn_at",
    "status", "created_at", "updated_at", "version",
)

ASSESSMENT_FIELDS = (
    "id", "student_account_id", "enrollment_id", "fee_item_id", "department_id",
    "assessed_amount_cents", "waived_amount_cents", "allocated_cents",
    "refunded_cents", "outstanding_cents", "payment_plan_id", "status",
    "created_at", "updated_at", "version",
)

PURCHASE_FIELDS = (
    "id", "student_account_id", "item_id", "amount_cents", "refunded_cents",
    "status", "created_at", "updated_at", "version",
)

PROGRAM_FIELDS = (
    "id", "school_year_id", "name", "waiver_pct_bp", "stacking_priority",
    "max_waived_per_student_cents", "eligibility_grade_min",
    "eligibility_grade_max", "status", "created_at", "updated_at", "version",
)

APPLICATION_FIELDS = (
    "id", "student_account_id", "waiver_program_id", "submitted_by_user_id",
    "reviewed_by_user_id", "status", "created_at", "updated_at", "version",
)

PAYMENT_FIELDS = (
    "id", "student_account_id", "amount_cents", "method", "idempotency_key",
    "overpayment_policy", "allocated_cents", "status", "created_at",
    "updated_at", "version",
)

ALLOCATION_FIELDS = (
    "id", "payment_id", "fee_assessment_id", "allocated_cents",
    "allocation_rule", "created_at",
)

PLAN_FIELDS = (
    "id", "student_account_id", "installment_count", "first_due_date",
    "interval_days", "covered_amount_cents", "installment_amount_cents",
    "status", "created_at", "updated_at", "version",
)

INSTALLMENT_FIELDS = (
    "id", "payment_plan_id", "sequence", "due_date", "amount_cents",
    "paid_cents", "status", "created_at", "updated_at", "version",
)

REFUND_FIELDS = (
    "id", "student_account_id", "fee_assessment_id", "purchase_id", "reason",
    "refund_cents", "status", "created_at", "updated_at", "version",
)

LEDGER_FIELDS = (
    "id", "student_account_id", "department_id", "entry_type", "amount_cents",
    "source_payment_id", "reconciliation_run_id", "created_at",
)

RUN_FIELDS = (
    "id", "school_year_id", "run_at", "entries_reconciled", "drift_detected",
    "status", "created_at", "updated_at", "version",
)

CASE_FIELDS = (
    "id", "student_account_id", "opened_at", "principal_cents", "aging_bucket",
    "written_off_cents", "approved_writeoff_cents", "status", "created_at",
    "updated_at", "version",
)

ACCOUNT_FIELDS = (
    "id", "school_year_id", "student_id", "assessed_cents", "waived_cents",
    "paid_cents", "balance_cents", "family_balance_cents", "posture",
    "last_posture_check_at", "created_at", "updated_at", "version",
)


def ser_year(y):
    return pub(y, YEAR_FIELDS)


def ser_student(s):
    return pub(s, STUDENT_FIELDS)


def ser_account(a):
    d = pub(a, ACCOUNT_FIELDS)
    d["family_balance_cents"] = family_balance(a)
    return d


def ser_department(d):
    out = pub(d, DEPARTMENT_FIELDS)
    # computed counters derived live from the ledger
    from core import dept_distributed
    distributed = dept_distributed(d["id"])
    out["distributed_cents"] = distributed
    out["reconciled_cents"] = d.get("reconciled_cents", 0)
    out["unreconciled_cents"] = distributed - d.get("reconciled_cents", 0)
    # reorder: computed fields after name
    return {
        "id": out["id"], "school_year_id": out["school_year_id"],
        "code": out["code"], "name": out["name"],
        "distributed_cents": out["distributed_cents"],
        "reconciled_cents": out["reconciled_cents"],
        "unreconciled_cents": out["unreconciled_cents"],
        "created_at": out["created_at"], "updated_at": out["updated_at"],
        "version": out["version"],
    }


def ser_offering(o):
    return pub(o, OFFERING_FIELDS)


def ser_fee_item(i):
    return pub(i, FEE_ITEM_FIELDS)


def ser_purchase_item(i):
    return pub(i, PURCHASE_ITEM_FIELDS)


def ser_enrollment(e):
    return pub(e, ENROLLMENT_FIELDS)


def ser_assessment(a):
    d = pub(a, ASSESSMENT_FIELDS)
    d["outstanding_cents"] = assessment_outstanding(a)
    return d


def ser_purchase(p):
    return pub(p, PURCHASE_FIELDS)


def ser_program(p):
    return pub(p, PROGRAM_FIELDS)


def ser_application(a):
    return pub(a, APPLICATION_FIELDS)


def ser_payment(p):
    return pub(p, PAYMENT_FIELDS)


def ser_allocation(a):
    return pub(a, ALLOCATION_FIELDS)


def ser_plan(p):
    return pub(p, PLAN_FIELDS)


def ser_installment(i):
    return pub(i, INSTALLMENT_FIELDS)


def ser_refund(r):
    return pub(r, REFUND_FIELDS)


def ser_ledger(e):
    return pub(e, LEDGER_FIELDS)


def ser_run(r):
    return pub(r, RUN_FIELDS)


def ser_case(c):
    d = pub(c, CASE_FIELDS)
    account = db.accounts.get(c["student_account_id"])
    year = db.years.get(account["school_year_id"]) if account else None
    if year is not None:
        d["aging_bucket"] = case_bucket(c, year)
    return d
