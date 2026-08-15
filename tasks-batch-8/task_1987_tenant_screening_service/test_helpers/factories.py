"""Payload factories — one per entity, input fields only (PRD §3–§4)."""
from .constants import CRITERIA_WINDOW, TEST_DEFAULTS


def create_landlord_payload(**overrides) -> dict:
    defaults = {"name": "Test Landlord", "contact_email": "landlord@x.com"}
    defaults.update(overrides)
    return defaults


def create_jurisdiction_rule_payload(**overrides) -> dict:
    defaults = {
        "state_code": "CA",
        "criminal_lookback_years": 7,
        "eviction_lookback_years": 7,
        "source_of_income_protected": False,
        "portable_report_acceptance_required": False,
        "effective_from": "2020-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_criteria_payload(**overrides) -> dict:
    defaults = {
        "name": "CR1",
        "disclosure_summary": "Standard criteria",
        "min_credit_score": TEST_DEFAULTS["MIN_CREDIT_SCORE"],
        "income_multiplier": TEST_DEFAULTS["INCOME_MULTIPLIER"],
        "guarantor_policy": "COMBINED_ALLOWED",
        "guarantor_income_multiplier": TEST_DEFAULTS["GUARANTOR_INCOME_MULTIPLIER"],
        "accepts_portable_reports": True,
        "accepts_voucher_income": True,
        "effective_from": CRITERIA_WINDOW["effective_from"],
        "effective_to": CRITERIA_WINDOW["effective_to"],
    }
    defaults.update(overrides)
    return defaults


def create_applicant_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Applicant",
        "dob": "1990-01-01T00:00:00Z",
        "email": "applicant@x.com",
        "ssn_last4": "1111",
        "residence_state": "TX",
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(**overrides) -> dict:
    defaults = {
        "unit_state_code": "TX",
        "monthly_rent_cents": TEST_DEFAULTS["RENT_CENTS"],
        "stated_monthly_income_cents": TEST_DEFAULTS["INCOME_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_record_payload(**overrides) -> dict:
    defaults = {
        "record_type": "EVICTION",
        "jurisdiction_state_code": "CA",
        "record_date": "2024-03-01T00:00:00Z",
        "description": "public record",
    }
    defaults.update(overrides)
    return defaults


def record_searches_payload(credit_score=TEST_DEFAULTS["CREDIT_SCORE"], records=None) -> dict:
    return {"credit_score": credit_score, "records": list(records or [])}


def verify_identity_payload(method="KNOWLEDGE_BASED", evidence_score=85) -> dict:
    return {"method": method, "evidence_score": evidence_score}


def create_guarantor_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Guarantor", "stated_monthly_income_cents": 300000}
    defaults.update(overrides)
    return defaults


def evaluate_guarantor_payload(verified_monthly_income_cents=300000, credit_score=720) -> dict:
    return {
        "verified_monthly_income_cents": verified_monthly_income_cents,
        "credit_score": credit_score,
    }


def create_income_verification_payload(**overrides) -> dict:
    defaults = {"employer_name": "Acme"}
    defaults.update(overrides)
    return defaults


def resolve_income_verified_payload(verified_monthly_income_cents=TEST_DEFAULTS["INCOME_CENTS"]) -> dict:
    return {"outcome": "VERIFIED", "verified_monthly_income_cents": verified_monthly_income_cents}


def resolve_income_failed_payload(failure_reason="employer unreachable") -> dict:
    return {"outcome": "FAILED", "failure_reason": failure_reason}


def file_dispute_payload(disputed_record_ids, reason_text="record is inaccurate") -> dict:
    return {"disputed_record_ids": list(disputed_record_ids), "reason_text": reason_text}


def resolve_dispute_payload(outcome="UPHELD", resolution_notes="reviewed") -> dict:
    return {"outcome": outcome, "resolution_notes": resolution_notes}
