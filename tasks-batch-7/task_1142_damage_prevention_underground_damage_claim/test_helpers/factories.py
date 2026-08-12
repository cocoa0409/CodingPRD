"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "COMPANY_NAME": "DigCo",
    "CONTACT_EMAIL": "d@x.com",
    "LOCATOR_COMPANY": "MarkCo",
    "LOCATOR_EMAIL": "m@x.com",
    "CONTRACT_REGION": "R1",
    "DIG_SITE_ADDRESS": "1 Test St",
    "WORK_START_AT": "2026-06-01T08:00:00Z",
    "WORK_END_AT": "2026-06-01T17:00:00Z",
    "OCCURRED_AT": "2026-05-02T09:00:00Z",
    "CAPTURED_AT": "2026-05-02T10:00:00Z",
    "FACILITY_TYPE": "GAS",
    "SEVERITY": "MAJOR",
    "EVIDENCE_TYPE": "PHOTO",
    "DESCRIPTION": "scene",
    "RESPONSE_CODE": "MARKED",
    "MARKS_COMPLETED_AT": "2026-05-02T07:00:00Z",
    "ROOT_CAUSE_CODE": "NO_TICKET",
    "CATEGORY": "LABOR",
    "QUANTITY": 10,
    "UNIT_COST_CENTS": 9000,
    "AMOUNT_CENTS": 1000,
    "REASON": "AMOUNT",
    "COURSE_CODE": "P101",
    "TITLE": "Probation remediation",
    "REQUIRED_FOR_STATUS": "PROBATION",
    "CREDIT_HOURS": 8,
}


def create_excavator_payload(**overrides) -> dict:
    defaults = {
        "company_name": DEFAULTS["COMPANY_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_locator_payload(**overrides) -> dict:
    defaults = {
        "company_name": DEFAULTS["LOCATOR_COMPANY"],
        "contact_email": DEFAULTS["LOCATOR_EMAIL"],
        "contract_region": DEFAULTS["CONTRACT_REGION"],
    }
    defaults.update(overrides)
    return defaults


def create_locate_ticket_payload(**overrides) -> dict:
    defaults = {
        "excavator_id": None,
        "dig_site_address": DEFAULTS["DIG_SITE_ADDRESS"],
        "work_start_at": DEFAULTS["WORK_START_AT"],
        "work_end_at": DEFAULTS["WORK_END_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_locate_response_payload(**overrides) -> dict:
    defaults = {
        "locate_ticket_id": None,
        "locator_id": None,
        "response_code": DEFAULTS["RESPONSE_CODE"],
        "marks_completed_at": DEFAULTS["MARKS_COMPLETED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_damage_case_payload(**overrides) -> dict:
    defaults = {
        "excavator_id": None,
        "dig_site_address": DEFAULTS["DIG_SITE_ADDRESS"],
        "facility_type": DEFAULTS["FACILITY_TYPE"],
        "severity": DEFAULTS["SEVERITY"],
        "occurred_at": DEFAULTS["OCCURRED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_evidence_item_payload(**overrides) -> dict:
    defaults = {
        "damage_case_id": None,
        "evidence_type": DEFAULTS["EVIDENCE_TYPE"],
        "captured_at": DEFAULTS["CAPTURED_AT"],
        "description": DEFAULTS["DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def create_fault_allocation_payload(**overrides) -> dict:
    defaults = {
        "damage_case_id": None,
        "root_cause_code": DEFAULTS["ROOT_CAUSE_CODE"],
        "expected_damage_case_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_cost_line_item_payload(**overrides) -> dict:
    defaults = {
        "damage_case_id": None,
        "category": DEFAULTS["CATEGORY"],
        "description": "line",
        "quantity": DEFAULTS["QUANTITY"],
        "unit_cost_cents": DEFAULTS["UNIT_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {
        "payer_type": "EXCAVATOR",
        "payer_id": None,
        "amount_cents": DEFAULTS["AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(**overrides) -> dict:
    defaults = {
        "target_type": "CLAIM_INVOICE",
        "target_id": None,
        "reason": DEFAULTS["REASON"],
    }
    defaults.update(overrides)
    return defaults


def create_regulatory_report_payload(**overrides) -> dict:
    defaults = {
        "report_type": "INCIDENT",
    }
    defaults.update(overrides)
    return defaults


def create_violation_record_payload(**overrides) -> dict:
    defaults = {
        "excavator_id": None,
        "damage_case_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_training_course_payload(**overrides) -> dict:
    defaults = {
        "course_code": DEFAULTS["COURSE_CODE"],
        "title": DEFAULTS["TITLE"],
        "required_for_status": DEFAULTS["REQUIRED_FOR_STATUS"],
        "credit_hours": DEFAULTS["CREDIT_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_training_assignment_payload(**overrides) -> dict:
    defaults = {
        "excavator_id": None,
        "course_id": None,
    }
    defaults.update(overrides)
    return defaults
