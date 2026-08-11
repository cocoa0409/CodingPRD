"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from . import constants as C

DEFAULT_SUPPORTING_DOCUMENT = {
    "document_type": "ARTICLES",
    "document_url": "https://docs.example.com/articles.pdf",
    "uploaded_at": "2026-01-15T00:00:00Z",
}

DEFAULT_AGENDA_ITEM = {
    "item_number": 1,
    "description": "Approve annual statement",
    "resolution_required": True,
}

_counter = {"n": 0}


def _uniq(prefix: str) -> str:
    _counter["n"] += 1
    return f"{prefix}-{_counter['n']}"


def create_captive_payload(**overrides) -> dict:
    defaults = {
        "captive_name": _uniq("Captive"),
        "domicile_jurisdiction": "VERMONT",
        "formation_date": "2026-01-15T00:00:00Z",
        "capitalization_amount": C.DEFAULT_CAPITALIZATION_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_domicile_filing_payload(**overrides) -> dict:
    defaults = {
        "filing_type": "INITIAL_FORMATION",
        "jurisdiction": "VERMONT",
        "supporting_documents": [dict(DEFAULT_SUPPORTING_DOCUMENT)],
    }
    defaults.update(overrides)
    return defaults


def create_program_payload(**overrides) -> dict:
    defaults = {
        "program_name": _uniq("Program"),
        "line_of_business": "GENERAL_LIABILITY",
        "policy_period_start": C.DEFAULT_POLICY_PERIOD_START,
        "policy_period_end": C.DEFAULT_POLICY_PERIOD_END,
        "aggregate_limit_cents": C.DEFAULT_AGGREGATE_LIMIT_CENTS,
        "per_occurrence_limit_cents": C.DEFAULT_PER_OCCURRENCE_LIMIT_CENTS,
        "attachment_point_cents": C.DEFAULT_ATTACHMENT_POINT_CENTS,
        "premium_budget_cents": C.DEFAULT_PREMIUM_BUDGET_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_fronting_payload(**overrides) -> dict:
    defaults = {
        "fronting_carrier_name": "FrontCo",
        "fronting_fee_pct": 0.08,
        "reinsurance_ceded_pct": 0.90,
    }
    defaults.update(overrides)
    return defaults


def create_collateral_payload(**overrides) -> dict:
    defaults = {
        "collateral_type": "CASH_ESCROW",
        "amount_cents": 1000000,
        "posted_date": "2026-05-01T00:00:00Z",
        "expiry_date": "2027-06-01T00:00:00Z",
        "issuing_institution": "First Bank",
    }
    defaults.update(overrides)
    return defaults


def create_operating_unit_payload(**overrides) -> dict:
    defaults = {
        "unit_name": _uniq("Unit"),
        "unit_code": _uniq("UC"),
        "exposure_basis": "REVENUE",
        "exposure_amount": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_payload(**overrides) -> dict:
    defaults = {
        "allocation_method": "EXPOSURE_PRO_RATA",
        "allocation_period_start": C.DEFAULT_POLICY_PERIOD_START,
        "allocation_period_end": C.DEFAULT_POLICY_PERIOD_END,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    defaults = {
        "claimant_name": "Test Claimant",
        "loss_date": C.DEFAULT_LOSS_DATE,
        "claimed_amount_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_tpa_payload(**overrides) -> dict:
    defaults = {
        "tpa_firm_name": "TPA Corp",
        "tpa_contact_email": "tpa@example.com",
        "authority_limit_cents": 100000,
        "fee_structure": "FLAT_FEE",
        "fee_amount_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_reserve_payload(**overrides) -> dict:
    defaults = {
        "reserve_type": "IBNR_RESERVE",
        "actuarial_method": "CHAIN_LADDER",
        "valuation_date": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_annual_statement_payload(**overrides) -> dict:
    defaults = {
        "statement_year": 2026,
        "investment_income_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_board_meeting_payload(**overrides) -> dict:
    defaults = {
        "meeting_date": "2026-06-15T00:00:00Z",
        "meeting_type": "ANNUAL",
        "directors_present": 15,
        "agenda_items": [dict(DEFAULT_AGENDA_ITEM)],
    }
    defaults.update(overrides)
    return defaults


def create_draft_minutes_payload(**overrides) -> dict:
    defaults = {
        "minutes_document_url": "https://docs.example.com/minutes.pdf",
        "resolutions_passed": [
            {"item_number": 1, "resolution_text": "Statement approved", "vote_result": "PASSED"}
        ],
    }
    defaults.update(overrides)
    return defaults


def create_tax_position_payload(**overrides) -> dict:
    defaults = {
        "tax_year": 2026,
        "position_type": "RISK_DISTRIBUTION",
        "position_description": "Annual risk distribution analysis",
    }
    defaults.update(overrides)
    return defaults
