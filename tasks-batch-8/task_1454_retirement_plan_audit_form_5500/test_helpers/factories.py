"""Payload factories — one per creatable resource, input fields only."""
from .constants import (
    DEFAULT_COMPENSATION_CENTS,
    DEFAULT_EIN,
    PLAN_YEAR_END_2025,
    PLAN_YEAR_START_2025,
)

_PLAN_COUNTER = {"n": 0}


def next_plan_number() -> str:
    """Monotonic three-digit plan numbers so tests never collide on
    (sponsor_ein, plan_number) when a test needs several engagements."""
    _PLAN_COUNTER["n"] += 1
    return f"{_PLAN_COUNTER['n'] % 1000:03d}"


def create_engagement_payload(**overrides) -> dict:
    defaults = {
        "sponsor_ein": DEFAULT_EIN,
        "plan_number": next_plan_number(),
        "plan_name": "Acme 401(k) Plan",
        "plan_year_start": PLAN_YEAR_START_2025,
        "plan_year_end": PLAN_YEAR_END_2025,
        "plan_type": "DC_401K",
        "funding_arrangement": "TRUST",
        "prior_year_schedule_type": "I",
    }
    defaults.update(overrides)
    return defaults


def create_participant_payload(engagement_id: str, external_ref: str = "P-001", **overrides) -> dict:
    defaults = {
        "engagement_id": engagement_id,
        "external_ref": external_ref,
        "eligibility_date": "2024-06-01",
        "entry_date": "2024-07-01",
        "is_eligible": True,
        "is_hce": False,
        "compensation_cy_cents": DEFAULT_COMPENSATION_CENTS,
        "deferral_amount_cy_cents": 0,
        "opening_balance_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def bulk_import_payload(engagement_id: str, count: int, prefix: str, **template_overrides) -> dict:
    template = {
        "eligibility_date": "2024-06-01",
        "entry_date": "2024-07-01",
        "is_eligible": True,
        "is_hce": False,
        "compensation_cy_cents": DEFAULT_COMPENSATION_CENTS,
        "deferral_amount_cy_cents": 0,
        "opening_balance_cents": 5_000_000,
    }
    template.update(template_overrides)
    return {
        "engagement_id": engagement_id,
        "count": count,
        "external_ref_prefix": prefix,
        "template": template,
    }


def create_contribution_payload(engagement_id: str, participant_id: str, **overrides) -> dict:
    defaults = {
        "engagement_id": engagement_id,
        "participant_id": participant_id,
        "type": "ELECTIVE_DEFERRAL",
        "payroll_date": "2025-06-16",
        "deposit_date": "2025-06-30",
        "amount_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_trust_statement_payload(engagement_id: str, **overrides) -> dict:
    defaults = {
        "engagement_id": engagement_id,
        "period_start": PLAN_YEAR_START_2025,
        "period_end": "2025-12-31",
        "custodian": "National Trust Co",
        "certification": "UNCERTIFIED",
        "reported_deposit_total_cents": 500_000,
    }
    defaults.update(overrides)
    return defaults


def create_test_result_payload(engagement_id: str, expected_engagement_version: int,
                               test_type: str = "ADP", **overrides) -> dict:
    defaults = {
        "engagement_id": engagement_id,
        "test_type": test_type,
        "expected_engagement_version": expected_engagement_version,
    }
    defaults.update(overrides)
    return defaults


def create_finding_payload(engagement_id: str, **overrides) -> dict:
    defaults = {
        "engagement_id": engagement_id,
        "category": "FILING_DEFECT",
        "severity": "LOW",
        "description": "manual finding",
    }
    defaults.update(overrides)
    return defaults


def create_corrective_action_payload(engagement_id: str, finding_id: str, **overrides) -> dict:
    defaults = {
        "engagement_id": engagement_id,
        "finding_id": finding_id,
        "action_type": "FEE_REDISCLOSURE",
        "principal_cents": 100,
        "planned_execution_date": "2026-04-01",
    }
    defaults.update(overrides)
    return defaults


def create_service_provider_fee_payload(engagement_id: str, provider_name: str, **overrides) -> dict:
    defaults = {
        "engagement_id": engagement_id,
        "provider_name": provider_name,
        "service_code": "RECORDKEEPING",
        "compensation_type": "DIRECT",
        "amount_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_filing_payload(engagement_id: str) -> dict:
    return {"engagement_id": engagement_id}


def create_schedule_entry_payload(filing_id: str, **overrides) -> dict:
    defaults = {
        "filing_id": filing_id,
        "schedule_type": "I",
        "line_item": "I-1 total assets",
        "amount_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_filing_extension_payload(filing_id: str, **overrides) -> dict:
    defaults = {
        "filing_id": filing_id,
        "filed_date": "2026-07-20",
    }
    defaults.update(overrides)
    return defaults


def create_correction_program_filing_payload(engagement_id: str, **overrides) -> dict:
    defaults = {
        "engagement_id": engagement_id,
        "program": "DFVCP",
        "linked_finding_ids": [],
        "government_fee_cents": 0,
    }
    defaults.update(overrides)
    return defaults
