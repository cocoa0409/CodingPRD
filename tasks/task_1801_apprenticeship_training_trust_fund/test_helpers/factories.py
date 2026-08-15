"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
from typing import Dict, List, Optional

from .constants import TEST_DEFAULTS


def create_trust_fund_payload(**overrides) -> dict:
    defaults = {"name": TEST_DEFAULTS["FUND_NAME"]}
    defaults.update(overrides)
    return defaults


def create_employer_payload(trust_fund_id: str, **overrides) -> dict:
    defaults = {
        "trust_fund_id": trust_fund_id,
        "legal_name": TEST_DEFAULTS["EMPLOYER_LEGAL_NAME"],
        "agreement_rate_cents_per_hour": TEST_DEFAULTS[
            "EMPLOYER_RATE_CENTS_PER_HOUR"
        ],
    }
    defaults.update(overrides)
    return defaults


def create_apprentice_payload(trust_fund_id: str, employer_id: str,
                              **overrides) -> dict:
    defaults = {
        "trust_fund_id": trust_fund_id,
        "employer_id": employer_id,
        "full_name": TEST_DEFAULTS["APPRENTICE_FULL_NAME"],
        "trade": TEST_DEFAULTS["APPRENTICE_TRADE"],
        "journeyman_base_rate_cents": TEST_DEFAULTS["JOURNEYMAN_BASE_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def report_line(apprentice_id: str, ojt_hours: float) -> dict:
    return {"apprentice_id": apprentice_id, "ojt_hours": ojt_hours}


def create_contribution_report_payload(employer_id: str, period_year: int,
                                       period_month: int, lines: List[dict],
                                       **overrides) -> dict:
    defaults = {
        "employer_id": employer_id,
        "period_year": period_year,
        "period_month": period_month,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_class_payload(trust_fund_id: str, **overrides) -> dict:
    defaults = {
        "trust_fund_id": trust_fund_id,
        "course_code": "CN-101",
        "instructor_user_id": TEST_DEFAULTS["INSTRUCTOR_USER_ID"],
        "instructor_name": TEST_DEFAULTS["INSTRUCTOR_NAME"],
        "instructor_rate_cents_per_hour": TEST_DEFAULTS[
            "INSTRUCTOR_RATE_CENTS_PER_HOUR"
        ],
        "facility": TEST_DEFAULTS["FACILITY"],
        "rti_credit_value": TEST_DEFAULTS["RTI_CREDIT_VALUE"],
        "capacity": TEST_DEFAULTS["CLASS_CAPACITY"],
        "start_minute": TEST_DEFAULTS["CLASS_START_MINUTE"],
        "end_minute": TEST_DEFAULTS["CLASS_END_MINUTE"],
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(class_id: str, apprentice_id: str) -> dict:
    return {"class_id": class_id, "apprentice_id": apprentice_id}


def complete_class_payload(attended_enrollment_ids: List[str]) -> dict:
    return {"attended_enrollment_ids": attended_enrollment_ids}


def create_pay_claim_payload(class_id: str, pay_basis: str,
                             actual_minutes: Optional[int] = None) -> dict:
    payload = {"class_id": class_id, "pay_basis": pay_basis}
    if actual_minutes is not None:
        payload["actual_minutes"] = actual_minutes
    return payload


def create_funding_allocation_payload(trust_fund_id: str, amount_cents: int,
                                      **overrides) -> dict:
    defaults = {
        "trust_fund_id": trust_fund_id,
        "category": "EQUIPMENT",
        "fiscal_year": TEST_DEFAULTS["FISCAL_YEAR"],
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def approve_allocation_payload(expected_trust_fund_version: int) -> dict:
    return {"expected_trust_fund_version": expected_trust_fund_version}


def create_equipment_purchase_payload(allocation_id: str, amount_cents: int,
                                      **overrides) -> dict:
    defaults = {
        "allocation_id": allocation_id,
        "description": "Training equipment",
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def submit_registration_payload(agency: str = "STATE") -> dict:
    return {"agency": agency}


def record_decision_payload(outcome: str, **overrides) -> dict:
    defaults: Dict = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def remit_payload(amount_tendered_cents: int) -> dict:
    return {"amount_tendered_cents": amount_tendered_cents}
