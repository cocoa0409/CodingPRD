"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "COUNTRY_CODE": "CH",
    "CPI_SCORE": 80,
    "LEGAL_NAME": "CH Tech GmbH",
    "INDUSTRY": "TECHNOLOGY",
    "TOUCHPOINT": "NONE",
    "CONTRACT_VALUE_CENTS": 500000,
    "START_DATE": "2026-05-02",
    "END_DATE": "2027-05-01",
    "DOCUMENT_REF": "s3://certs/doc.pdf",
    "COURSE_CODE": "ABAC-101",
    "FX_RATE": 1.0,
}

# Canonical scoring policy (PRD §3.1): weights sum to 100; inclusive tier bounds.
POLICY_P1 = {
    "w_country": 50,
    "w_industry": 30,
    "w_touchpoint": 20,
    "tier_medium_min": 40,
    "tier_high_min": 70,
    "tier_critical_min": 90,
    "commission_base_cap_pct": 15,
    "commission_hard_cap_pct": 25,
}


def country_profile_payload(**overrides) -> dict:
    defaults = {"country_code": DEFAULTS["COUNTRY_CODE"], "cpi_score": DEFAULTS["CPI_SCORE"]}
    defaults.update(overrides)
    return defaults


def policy_payload(**overrides) -> dict:
    defaults = dict(POLICY_P1)
    defaults.update(overrides)
    return defaults


def third_party_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "country_code": DEFAULTS["COUNTRY_CODE"],
        "industry": DEFAULTS["INDUSTRY"],
        "government_touchpoint": DEFAULTS["TOUCHPOINT"],
    }
    defaults.update(overrides)
    return defaults


def questionnaire_answers_payload(**overrides) -> dict:
    defaults = {
        "government_ownership_pct": 0,
        "has_facilitation_payments": False,
        "uses_sub_agents": False,
    }
    defaults.update(overrides)
    return defaults


def red_flag_payload(**overrides) -> dict:
    defaults = {"severity": "MEDIUM", "description": "manual review finding"}
    defaults.update(overrides)
    return defaults


def contract_payload(**overrides) -> dict:
    defaults = {
        "contract_value_cents": DEFAULTS["CONTRACT_VALUE_CENTS"],
        "start_date": DEFAULTS["START_DATE"],
        "end_date": DEFAULTS["END_DATE"],
    }
    defaults.update(overrides)
    return defaults


def certification_payload(**overrides) -> dict:
    defaults = {"cert_type": "ANNUAL_ABAC"}
    defaults.update(overrides)
    return defaults


def payment_request_payload(**overrides) -> dict:
    defaults = {"payment_type": "COMMISSION", "amount_cents": 50000}
    defaults.update(overrides)
    return defaults


def gift_entry_payload(**overrides) -> dict:
    defaults = {
        "entry_type": "GIFT",
        "recipient_is_government_official": True,
        "value_cents": 5000,
        "fx_rate_to_usd": DEFAULTS["FX_RATE"],
        "event_date": "2026-05-10",
    }
    defaults.update(overrides)
    return defaults


def audit_exercise_payload(**overrides) -> dict:
    defaults = {
        "fieldwork_start_date": "2026-05-15",
        "fieldwork_end_date": "2026-05-30",
    }
    defaults.update(overrides)
    return defaults


def training_assignment_payload(**overrides) -> dict:
    defaults = {
        "assignee_user_id": "u_sp1",
        "course_code": DEFAULTS["COURSE_CODE"],
        "due_date": "2026-05-15",
    }
    defaults.update(overrides)
    return defaults
