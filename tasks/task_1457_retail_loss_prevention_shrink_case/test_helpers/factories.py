"""Payload factories — one per creatable resource, input fields only."""

DEFAULTS = {
    "STORE_NUMBER": "S-0001",
    "STORE_NAME": "Test Store",
    "REGION_CODE": "R1",
    "EMPLOYEE_REF": "E-0001",
    "EMPLOYEE_NAME": "Test Employee",
    "REGISTER_REF": "R-1",
    "EXCEPTION_TYPE": "HIGH_VALUE_VOID",
    "AMOUNT_CENTS": 10000,
    "OCCURRED_AT": "2026-07-15T10:00:00Z",
    "SUBJECT_TYPE": "EXTERNAL",
    "MANUAL_LOSS_CENTS": 1000,
    "EVIDENCE_TYPE": "PHOTO",
    "CAPTURED_AT": "2026-07-15T10:00:00Z",
    "RETENTION_CLASS": "STANDARD",
    "INTERVIEW_START": "2026-08-02T09:00:00Z",
    "INTERVIEW_END": "2026-08-02T10:00:00Z",
    "DEMAND_BASIS": "ACTUAL_LOSS",
    "PAYMENT_METHOD": "CASH",
    "GROUP_NAME": "Ring Test",
    "LINK_SCORE": 80,
    "PERIOD_START": "2026-07-01T00:00:00Z",
    "PERIOD_END": "2026-09-30T23:59:59Z",
    "BOOK_INVENTORY_CENTS": 5_000_000,
    "PERIOD_SALES_CENTS": 4_000_000,
    "JURISDICTION_CODE": "CA-LA",
}


def create_store_payload(**overrides) -> dict:
    defaults = {
        "store_number": DEFAULTS["STORE_NUMBER"],
        "name": DEFAULTS["STORE_NAME"],
        "region_code": DEFAULTS["REGION_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_employee_payload(store_id, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "employee_ref": DEFAULTS["EMPLOYEE_REF"],
        "full_name": DEFAULTS["EMPLOYEE_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(store_id, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "register_ref": DEFAULTS["REGISTER_REF"],
        "txn_ref": "TXN-1",
        "exception_type": DEFAULTS["EXCEPTION_TYPE"],
        "amount_cents": DEFAULTS["AMOUNT_CENTS"],
        "occurred_at": DEFAULTS["OCCURRED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(store_id, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "subject_type": DEFAULTS["SUBJECT_TYPE"],
        "manual_loss_cents": DEFAULTS["MANUAL_LOSS_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_interview_payload(case_id, interviewer_id, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "interviewer_id": interviewer_id,
        "scheduled_start": DEFAULTS["INTERVIEW_START"],
        "scheduled_end": DEFAULTS["INTERVIEW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_evidence_payload(case_id, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "evidence_type": DEFAULTS["EVIDENCE_TYPE"],
        "captured_at": DEFAULTS["CAPTURED_AT"],
        "retention_class": DEFAULTS["RETENTION_CLASS"],
    }
    defaults.update(overrides)
    return defaults


def create_demand_payload(case_id, expected_case_version, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "basis": DEFAULTS["DEMAND_BASIS"],
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(demand_id, **overrides) -> dict:
    defaults = {
        "demand_id": demand_id,
        "amount_cents": DEFAULTS["AMOUNT_CENTS"],
        "method": DEFAULTS["PAYMENT_METHOD"],
    }
    defaults.update(overrides)
    return defaults


def create_orc_group_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["GROUP_NAME"]}
    defaults.update(overrides)
    return defaults


def create_case_link_payload(case_id, orc_group_id, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "orc_group_id": orc_group_id,
        "link_score": DEFAULTS["LINK_SCORE"],
    }
    defaults.update(overrides)
    return defaults


def create_shrink_period_payload(store_id, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
        "book_inventory_cents": DEFAULTS["BOOK_INVENTORY_CENTS"],
        "period_sales_cents": DEFAULTS["PERIOD_SALES_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_referral_packet_payload(case_id, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "jurisdiction_code": DEFAULTS["JURISDICTION_CODE"],
    }
    defaults.update(overrides)
    return defaults
