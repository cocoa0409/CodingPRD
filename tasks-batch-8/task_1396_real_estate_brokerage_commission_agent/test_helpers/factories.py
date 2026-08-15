"""Payload factories — input fields only, PRD §3/§4."""

_LICENSE_COUNTER = [0]


def _next_license(prefix: str = "LIC-T") -> str:
    _LICENSE_COUNTER[0] += 1
    return f"{prefix}-{_LICENSE_COUNTER[0]:05d}"


def create_agent_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Agent",
        "email": f"agent{_LICENSE_COUNTER[0]}@example.com",
        "license_number": _next_license(),
        "joined_at": "2025-09-01",
    }
    defaults.update(overrides)
    return defaults


def create_plan_p1_payload(**overrides) -> dict:
    """The shared plan P1 used by the design indices."""
    defaults = {
        "name": "P1",
        "royalty_pct": 0.06,
        "royalty_cap_cents": 300000,
        "eo_fee_cents": 6000,
        "transaction_fee_cents": 25000,
        "mentor_split_pct": 0.10,
        "mentor_deal_count": 3,
        "tiers": [
            {"threshold_company_dollar_cents": 2500000, "broker_split_pct": 0.30},
            {"threshold_company_dollar_cents": 10**18, "broker_split_pct": 0.0},
        ],
    }
    defaults.update(overrides)
    return defaults


def create_plan_p2_payload(**overrides) -> dict:
    """The shared plan P2 used by the design indices."""
    defaults = {
        "name": "P2",
        "royalty_pct": 0.06,
        "royalty_cap_cents": 300000,
        "eo_fee_cents": 7000,
        "transaction_fee_cents": 20000,
        "mentor_split_pct": 0.0,
        "mentor_deal_count": 0,
        "tiers": [
            {"threshold_company_dollar_cents": 2000000, "broker_split_pct": 0.25},
            {"threshold_company_dollar_cents": 10**18, "broker_split_pct": 0.0},
        ],
    }
    defaults.update(overrides)
    return defaults


def create_deal_payload(agent_id, **overrides) -> dict:
    defaults = {
        "agent_id": agent_id,
        "address": "1 Main St",
        "gross_commission_cents": 1000000,
        "closing_date": "2026-01-15",
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(plan_id, effective_from, expected_agent_version) -> dict:
    return {
        "plan_id": plan_id,
        "effective_from": effective_from,
        "expected_agent_version": expected_agent_version,
    }


def create_debit_adjustment_payload(amount_cents, reason="manual adjustment") -> dict:
    return {"amount_cents": amount_cents, "reason": reason}


def create_tax_form_payload(tax_year) -> dict:
    return {"tax_year": tax_year}
