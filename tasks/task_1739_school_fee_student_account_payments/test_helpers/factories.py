"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "YEAR_LABEL": "2026-27",
    "YEAR_START": "2026-08-01",
    "YEAR_END": "2027-06-30",
    "REFUND_FULL_DAYS": 2,
    "REFUND_PARTIAL_DAYS": 10,
    "PARTIAL_REFUND_PCT_BP": 5000,
    "PLAN_MIN_CENTS": 1000,
    "PLAN_MAX_INSTALLMENTS": 6,
    "WRITEOFF_MAX_CENTS": 100000,
    "AGING_INTERVAL_DAYS": 10,
    "GRAD_HOLD_THRESHOLD_CENTS": 5000,
    "DEPARTMENT_CODE": "SCI",
    "DEPARTMENT_NAME": "Science",
    "FEE_NAME": "Lab Fee",
    "FEE_AMOUNT": 1000,
    "ITEM_NAME": "Yearbook",
    "ITEM_AMOUNT": 2000,
    "ITEM_CAP": 5,
    "OFFERING_KIND": "COURSE",
    "OFFERING_TITLE": "Chem",
    "OFFERING_START": "2026-09-01",
    "OFFERING_END": "2026-12-15",
    "OFFERING_CAPACITY": 30,
    "EXTERNAL_REF": "S-1",
    "FULL_NAME": "Ada",
    "GRADE": 10,
    "FAMILY_ID": "fam-a",
    "PROGRAM_NAME": "P",
    "WAIVER_PCT_BP": 5000,
    "STACKING_PRIORITY": 1,
    "MAX_WAIVED": 100000,
    "GRADE_MIN": 9,
    "GRADE_MAX": 12,
    "PAYMENT_METHOD": "CARD",
}


def create_school_year_payload(**overrides) -> dict:
    defaults = {
        "label": DEFAULTS["YEAR_LABEL"],
        "start_date": DEFAULTS["YEAR_START"],
        "end_date": DEFAULTS["YEAR_END"],
        "refund_full_days": DEFAULTS["REFUND_FULL_DAYS"],
        "refund_partial_days": DEFAULTS["REFUND_PARTIAL_DAYS"],
        "partial_refund_pct_bp": DEFAULTS["PARTIAL_REFUND_PCT_BP"],
        "payment_plan_min_cents": DEFAULTS["PLAN_MIN_CENTS"],
        "payment_plan_max_installments": DEFAULTS["PLAN_MAX_INSTALLMENTS"],
        "writeoff_max_cents": DEFAULTS["WRITEOFF_MAX_CENTS"],
        "aging_interval_days": DEFAULTS["AGING_INTERVAL_DAYS"],
        "graduation_hold_threshold_cents": DEFAULTS["GRAD_HOLD_THRESHOLD_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_department_payload(**overrides) -> dict:
    defaults = {"code": DEFAULTS["DEPARTMENT_CODE"], "name": DEFAULTS["DEPARTMENT_NAME"]}
    defaults.update(overrides)
    return defaults


def create_fee_catalog_item_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["FEE_NAME"],
        "amount_cents": DEFAULTS["FEE_AMOUNT"],
        "waiverable": True,
        "refundable": True,
    }
    defaults.update(overrides)
    return defaults


def create_optional_purchase_item_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["ITEM_NAME"],
        "amount_cents": DEFAULTS["ITEM_AMOUNT"],
        "refundable": True,
        "inventory_cap": DEFAULTS["ITEM_CAP"],
    }
    defaults.update(overrides)
    return defaults


def create_offering_payload(**overrides) -> dict:
    defaults = {
        "kind": DEFAULTS["OFFERING_KIND"],
        "title": DEFAULTS["OFFERING_TITLE"],
        "start_date": DEFAULTS["OFFERING_START"],
        "end_date": DEFAULTS["OFFERING_END"],
        "capacity": DEFAULTS["OFFERING_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(**overrides) -> dict:
    defaults = {
        "external_ref": DEFAULTS["EXTERNAL_REF"],
        "full_name": DEFAULTS["FULL_NAME"],
        "grade_level": DEFAULTS["GRADE"],
        "family_id": DEFAULTS["FAMILY_ID"],
    }
    defaults.update(overrides)
    return defaults


def create_student_account_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_fee_assessment_payload(**overrides) -> dict:
    defaults = {"assessed_amount_cents": 3000}
    defaults.update(overrides)
    return defaults


def create_purchase_payload(**overrides) -> dict:
    defaults = {"method": DEFAULTS["PAYMENT_METHOD"]}
    defaults.update(overrides)
    return defaults


def create_waiver_program_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PROGRAM_NAME"],
        "waiver_pct_bp": DEFAULTS["WAIVER_PCT_BP"],
        "stacking_priority": DEFAULTS["STACKING_PRIORITY"],
        "max_waived_per_student_cents": DEFAULTS["MAX_WAIVED"],
        "eligibility_grade_min": DEFAULTS["GRADE_MIN"],
        "eligibility_grade_max": DEFAULTS["GRADE_MAX"],
    }
    defaults.update(overrides)
    return defaults


def create_waiver_application_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 3000,
        "method": DEFAULTS["PAYMENT_METHOD"],
        "idempotency_key": "k1",
    }
    defaults.update(overrides)
    return defaults


def create_payment_plan_payload(**overrides) -> dict:
    defaults = {
        "installment_count": 2,
        "first_due_date": "2026-09-05",
        "interval_days": 30,
    }
    defaults.update(overrides)
    return defaults
