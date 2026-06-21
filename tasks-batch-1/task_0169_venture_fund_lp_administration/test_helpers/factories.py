"""Payload factories — one per entity, input fields only.

Only fields the client supplies (source: input) appear here. Computed,
system, and common fields (id, status, version, drawn_cents, etc.) are
never sent. Optional fields with PRD-declared defaults are omitted from the
base payload and only added via overrides so tests can exercise the default.
"""

DEFAULTS = {
    "FUND_NAME": "Test Fund",
    "VINTAGE_YEAR": 2024,
    "TARGET_SIZE_CENTS": 10_000_000,
    "MGMT_FEE_RATE_BPS": 200,
    "CARRY_RATE_BPS": 2000,
    "PREF_RATE_BPS": 800,
    "COMMITTED_CENTS": 5_000_000,
    "DUE_DATE": "2030-02-01T00:00:00Z",
    "AS_OF_DATE": "2024-06-30T00:00:00Z",
    "FAIR_VALUE_CENTS": 4_000_000,
    "COST_BASIS_CENTS": 5_000_000,
    "OWNERSHIP_PCT_BPS": 1000,
    "GROSS_AMOUNT_CENTS": 1_000_000,
}


def create_fund_payload(**overrides) -> dict:
    """Required: name, vintage_year, target_size_cents, mgmt_fee_rate_bps,
    carry_rate_bps, pref_rate_bps. Optional (defaults applied server-side):
    gp_catchup_rate_bps, recycling_cap_pct_bps, fee_offset_pct_bps."""
    defaults = {
        "name": DEFAULTS["FUND_NAME"],
        "vintage_year": DEFAULTS["VINTAGE_YEAR"],
        "target_size_cents": DEFAULTS["TARGET_SIZE_CENTS"],
        "mgmt_fee_rate_bps": DEFAULTS["MGMT_FEE_RATE_BPS"],
        "carry_rate_bps": DEFAULTS["CARRY_RATE_BPS"],
        "pref_rate_bps": DEFAULTS["PREF_RATE_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_limited_partner_payload(**overrides) -> dict:
    """Required: legal_name, lp_type, tax_id_last4. Optional: is_tax_exempt."""
    defaults = {
        "legal_name": "Test LP",
        "lp_type": "INSTITUTION",
        "tax_id_last4": "0000",
    }
    defaults.update(overrides)
    return defaults


def create_commitment_payload(fund_id, lp_id, **overrides) -> dict:
    """Required: fund_id, lp_id, committed_cents."""
    defaults = {
        "fund_id": fund_id,
        "lp_id": lp_id,
        "committed_cents": DEFAULTS["COMMITTED_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_capital_call_payload(fund_id, expected_fund_version, **overrides) -> dict:
    """Required: fund_id, purpose, called_amount_cents, due_date,
    expected_fund_version."""
    defaults = {
        "fund_id": fund_id,
        "purpose": "INVESTMENT",
        "called_amount_cents": DEFAULTS["GROSS_AMOUNT_CENTS"],
        "due_date": DEFAULTS["DUE_DATE"],
        "expected_fund_version": expected_fund_version,
    }
    defaults.update(overrides)
    return defaults


def create_portfolio_company_payload(**overrides) -> dict:
    """Required: name, sector."""
    defaults = {"name": "Test Co", "sector": "SaaS"}
    defaults.update(overrides)
    return defaults


def create_investment_payload(fund_id, portfolio_company_id, **overrides) -> dict:
    """Required: fund_id, portfolio_company_id, cost_basis_cents,
    ownership_pct_bps."""
    defaults = {
        "fund_id": fund_id,
        "portfolio_company_id": portfolio_company_id,
        "cost_basis_cents": DEFAULTS["COST_BASIS_CENTS"],
        "ownership_pct_bps": DEFAULTS["OWNERSHIP_PCT_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_valuation_mark_payload(investment_id, **overrides) -> dict:
    """Required: investment_id, as_of_date, fair_value_cents, methodology."""
    defaults = {
        "investment_id": investment_id,
        "as_of_date": DEFAULTS["AS_OF_DATE"],
        "fair_value_cents": DEFAULTS["FAIR_VALUE_CENTS"],
        "methodology": "DCF",
    }
    defaults.update(overrides)
    return defaults


def create_distribution_event_payload(fund_id, source_investment_id,
                                      expected_fund_version, **overrides) -> dict:
    """Required: fund_id, source_investment_id, gross_amount_cents,
    distribution_type, expected_fund_version. Optional: recyclable."""
    defaults = {
        "fund_id": fund_id,
        "source_investment_id": source_investment_id,
        "gross_amount_cents": DEFAULTS["GROSS_AMOUNT_CENTS"],
        "distribution_type": "CAPITAL_GAIN",
        "expected_fund_version": expected_fund_version,
    }
    defaults.update(overrides)
    return defaults


def create_fee_accrual_payload(period_start, period_end, **overrides) -> dict:
    """Required: period_start, period_end."""
    defaults = {"period_start": period_start, "period_end": period_end}
    defaults.update(overrides)
    return defaults


def create_side_letter_payload(fund_id, lp_id, mfn_rank, **overrides) -> dict:
    """Required: fund_id, lp_id, mfn_rank. Optional: fee_discount_bps,
    excused_purposes."""
    defaults = {"fund_id": fund_id, "lp_id": lp_id, "mfn_rank": mfn_rank}
    defaults.update(overrides)
    return defaults


def fund_allocation_payload(paid_amount_cents) -> dict:
    """Input for POST /capital-call-allocations/{id}/fund."""
    return {"paid_amount_cents": paid_amount_cents}


def realize_investment_payload(realized_proceeds_cents) -> dict:
    """Input for POST /investments/{id}/realize."""
    return {"realized_proceeds_cents": realized_proceeds_cents}
