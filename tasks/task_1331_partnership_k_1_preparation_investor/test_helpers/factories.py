"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools
import uuid

from .constants import CANONICAL_FUND

_name_counter = itertools.count(1)


def _unique_ein() -> str:
    """Fund ein must be unique across funds (PRD §3.1)."""
    return f"22-{next(_name_counter):07d}"


def create_fund_payload(**overrides) -> dict:
    defaults = dict(CANONICAL_FUND)
    defaults.update({
        "legal_name": f"Fund {next(_name_counter)}",
        "ein": _unique_ein(),
    })
    defaults.update(overrides)
    return defaults


def create_tax_year_payload(fund_id, **overrides) -> dict:
    defaults = {
        "fund_id": fund_id,
        "year": 2025,
        "gross_ordinary_income_cents": 1000000,
        "capital_gain_cents": 0,
        "interest_income_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_partner_payload(fund_id, **overrides) -> dict:
    defaults = {
        "fund_id": fund_id,
        "legal_name": f"Partner {uuid.uuid4().hex[:8]}",
        "partner_type": "US_INDIVIDUAL",
        "partner_class": "LIMITED",
        "residency_state": "CA",
        "ownership_pct_bps": 10000,
        "capital_commitment_cents": 1,
        "admission_date": "2025-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_capital_event_payload(partner_id, tax_year_id, **overrides) -> dict:
    defaults = {
        "partner_id": partner_id,
        "tax_year_id": tax_year_id,
        "event_type": "CONTRIBUTION",
        "amount_cents": 100000,
        "effective_date": "2025-01-15",
    }
    defaults.update(overrides)
    return defaults


def create_transfer_payload(fund_id, transferor_partner_id, transferee_partner_id, **overrides) -> dict:
    defaults = {
        "fund_id": fund_id,
        "transferor_partner_id": transferor_partner_id,
        "transferee_partner_id": transferee_partner_id,
        "pct_bps": 100,
        "effective_date": "2025-03-01",
        "settlement_date": "2025-03-05",
    }
    defaults.update(overrides)
    return defaults


def create_allocation_run_payload(tax_year_id, expected_tax_year_version, **overrides) -> dict:
    defaults = {
        "tax_year_id": tax_year_id,
        "run_kind": "FINAL",
        "expected_tax_year_version": expected_tax_year_version,
    }
    defaults.update(overrides)
    return defaults


def create_special_allocation_payload(tax_year_id, partner_id, **overrides) -> dict:
    defaults = {
        "tax_year_id": tax_year_id,
        "partner_id": partner_id,
        "category": "ORDINARY",
        "target_pct_bps": 1000,
        "effective_from": "2025-01-01",
        "effective_to": "2026-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_composite_filing_payload(tax_year_id, **overrides) -> dict:
    defaults = {
        "tax_year_id": tax_year_id,
        "state_code": "NY",
        "apportionment_pct_bps": 5000,
        "composite_rate_bps": 800,
        "min_income_cents": 1,
    }
    defaults.update(overrides)
    return defaults


def create_withholding_accrual_payload(tax_year_id, **overrides) -> dict:
    defaults = {
        "tax_year_id": tax_year_id,
        "quarter": 1,
        "method": "CURRENT_ACTUAL",
    }
    defaults.update(overrides)
    return defaults


def create_k1_amendment_payload(k1_package_id, **overrides) -> dict:
    defaults = {
        "k1_package_id": k1_package_id,
        "reason": "ALLOCATION_CHANGE",
    }
    defaults.update(overrides)
    return defaults


def create_ticket_payload(partner_id, **overrides) -> dict:
    defaults = {
        "partner_id": partner_id,
        "category": "ALLOCATION_QUESTION",
        "subject": "Question",
    }
    defaults.update(overrides)
    return defaults
