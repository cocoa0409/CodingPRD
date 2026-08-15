"""Payload factories — one per creatable resource, input fields only.

Canonical jurisdiction fixtures used throughout the suite:
  J1 "US-DE": FIXED_MONTH_DAY 12/31, grace 10, SHARES_TIERED, CALENDAR_DAYS,
              penalty base 12500 / cap 50000, report fee 5000, cert 5000,
              agent notice 30, forfeiture window 120.
  J2 "US-CA": FORMATION_ANNIVERSARY, grace 0, franchise NONE, BUSINESS_DAYS,
              penalty base 10000 / cap 25000, report fee 2500, cert 4000,
              agent notice 45, forfeiture window 90.
  J3 "US-NV": FIXED_MONTH_DAY 9/30, grace 15, franchise NONE, CALENDAR_DAYS,
              penalty base 8000 / cap 20000, report fee 3000, cert 3000,
              agent notice 30, forfeiture window 60.
"""
from typing import Any, Dict, Optional


def create_jurisdiction_payload(**overrides) -> Dict[str, Any]:
    """Canonical J1 (US-DE) jurisdiction payload."""
    defaults: Dict[str, Any] = {
        "code": "US-DE",
        "name": "Delaware",
        "annual_report_due_rule": "FIXED_MONTH_DAY",
        "annual_report_due_month": 12,
        "annual_report_due_day": 31,
        "grace_period_days": 10,
        "franchise_tax_method": "SHARES_TIERED",
        "late_penalty_base_cents": 12500,
        "late_penalty_cap_cents": 50000,
        "penalty_day_counting": "CALENDAR_DAYS",
        "report_fee_cents": 5000,
        "cert_fee_cents": 5000,
        "ra_resignation_notice_days": 30,
        "forfeiture_window_days": 120,
    }
    defaults.update(overrides)
    return defaults


def create_jurisdiction_ca_payload(**overrides) -> Dict[str, Any]:
    """Canonical J2 (US-CA): anniversary due rule, no franchise tax, business days."""
    defaults: Dict[str, Any] = {
        "code": "US-CA",
        "name": "California",
        "annual_report_due_rule": "FORMATION_ANNIVERSARY",
        "grace_period_days": 0,
        "franchise_tax_method": "NONE",
        "late_penalty_base_cents": 10000,
        "late_penalty_cap_cents": 25000,
        "penalty_day_counting": "BUSINESS_DAYS",
        "report_fee_cents": 2500,
        "cert_fee_cents": 4000,
        "ra_resignation_notice_days": 45,
        "forfeiture_window_days": 90,
    }
    defaults.update(overrides)
    return defaults


def create_jurisdiction_nv_payload(**overrides) -> Dict[str, Any]:
    """Canonical J3 (US-NV): fixed 9/30, no franchise tax."""
    defaults: Dict[str, Any] = {
        "code": "US-NV",
        "name": "Nevada",
        "annual_report_due_rule": "FIXED_MONTH_DAY",
        "annual_report_due_month": 9,
        "annual_report_due_day": 30,
        "grace_period_days": 15,
        "franchise_tax_method": "NONE",
        "late_penalty_base_cents": 8000,
        "late_penalty_cap_cents": 20000,
        "penalty_day_counting": "CALENDAR_DAYS",
        "report_fee_cents": 3000,
        "cert_fee_cents": 3000,
        "ra_resignation_notice_days": 30,
        "forfeiture_window_days": 60,
    }
    defaults.update(overrides)
    return defaults


def create_registered_agent_payload(jurisdiction_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "name": "DE Agent Co",
        "jurisdiction_id": jurisdiction_id,
        "address": "1 Agent Way",
    }
    defaults.update(overrides)
    return defaults


def create_officer_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "full_name": "Olivia Ortiz",
        "email": "oo@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_entity_payload(formation_jurisdiction_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "legal_name": "Acme Holdings Inc",
        "entity_type": "CORPORATION",
        "formation_jurisdiction_id": formation_jurisdiction_id,
        "formation_date": "2025-06-15",
    }
    defaults.update(overrides)
    return defaults


def create_agent_appointment_payload(
    agent_id: str, jurisdiction_id: str, **overrides
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "agent_id": agent_id,
        "jurisdiction_id": jurisdiction_id,
        "start_date": "2025-06-15",
    }
    defaults.update(overrides)
    return defaults


def create_resolution_payload(
    resolution_type: str, payload: Dict[str, Any], effective_date: str, **overrides
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "resolution_type": resolution_type,
        "payload": payload,
        "effective_date": effective_date,
    }
    defaults.update(overrides)
    return defaults


def create_grant_payload(
    officer_id: str,
    scope: str,
    max_amount_cents: int,
    effective_date: str,
    expiry_date: str,
    delegated_from_grant_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "officer_id": officer_id,
        "scope": scope,
        "max_amount_cents": max_amount_cents,
        "effective_date": effective_date,
        "expiry_date": expiry_date,
    }
    if delegated_from_grant_id is not None:
        defaults["delegated_from_grant_id"] = delegated_from_grant_id
    defaults.update(overrides)
    return defaults


def create_qualification_payload(
    jurisdiction_id: str, agent_appointment_id: str, **overrides
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "jurisdiction_id": jurisdiction_id,
        "agent_appointment_id": agent_appointment_id,
    }
    defaults.update(overrides)
    return defaults


def create_certificate_request_payload(
    jurisdiction_id: str, delivery_speed: str = "STANDARD", **overrides
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "jurisdiction_id": jurisdiction_id,
        "delivery_speed": delivery_speed,
    }
    defaults.update(overrides)
    return defaults


def create_ownership_record_payload(
    parent_entity_id: str,
    subsidiary_entity_id: str,
    percentage_bps: int,
    effective_date: str,
    expected_entity_version: int,
    supersedes_record_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "parent_entity_id": parent_entity_id,
        "subsidiary_entity_id": subsidiary_entity_id,
        "percentage_bps": percentage_bps,
        "effective_date": effective_date,
        "expected_entity_version": expected_entity_version,
    }
    if supersedes_record_id is not None:
        defaults["supersedes_record_id"] = supersedes_record_id
    defaults.update(overrides)
    return defaults


def create_verify_payload(
    entity_id: str,
    officer_id: str,
    scope: str,
    amount_cents: int,
    as_of_date: str,
    **overrides,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "entity_id": entity_id,
        "officer_id": officer_id,
        "scope": scope,
        "amount_cents": amount_cents,
        "as_of_date": as_of_date,
    }
    defaults.update(overrides)
    return defaults
