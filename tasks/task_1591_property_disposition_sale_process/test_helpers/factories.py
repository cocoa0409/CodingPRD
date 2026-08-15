"""Payload factories — one per creatable resource, input fields only.

Named asset builders encode the canonical property fixtures used across the
suite: a leveraged yield-maintenance office asset, a step-down industrial
asset, an unlevered round-number multifamily asset, a lockout-restricted
asset, a low-price retail asset, and the tier-boundary retail asset.
"""

# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------

def create_asset_payload(**overrides) -> dict:
    """Baseline: an unlevered asset (no loan block engaged)."""
    defaults = {
        "name": "Alpha",
        "market": "Dallas",
        "asset_type": "OFFICE",
        "noi_cents": 250_000_000,
        "noi_growth_bps": 300,
        "book_value_cents": 4_000_000_000,
        "guidance_price_cents": 5_000_000_000,
        "loan_balance_cents": 0,
        "loan_rate_bps": 0,
        "loan_maturity_date": None,
        "monthly_debt_service_cents": 0,
        "remaining_term_months": 0,
        "prepayment_type": "NONE",
        "defeasance_allowed": False,
        "defeasance_fee_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def alpha_asset_payload(**overrides) -> dict:
    """Leveraged office asset: yield-maintenance loan, defeasance permitted,
    lockout already in the past at the default logical clock."""
    payload = create_asset_payload(
        name="Alpha",
        market="Dallas",
        asset_type="OFFICE",
        noi_cents=250_000_000,
        noi_growth_bps=300,
        book_value_cents=4_000_000_000,
        guidance_price_cents=5_000_000_000,
        loan_balance_cents=3_000_000_000,
        loan_rate_bps=650,
        loan_maturity_date="2030-06-30T00:00:00Z",
        monthly_debt_service_cents=19_000_000,
        remaining_term_months=46,
        prepayment_type="YIELD_MAINTENANCE",
        prepayment_lockout_until="2026-01-01T00:00:00Z",
        defeasance_allowed=True,
        defeasance_fee_cents=50_000_000,
    )
    payload.update(overrides)
    return payload


def delta_asset_payload(**overrides) -> dict:
    """Leveraged industrial asset with a STEP_DOWN prepayment schedule."""
    payload = create_asset_payload(
        name="Delta",
        market="Phoenix",
        asset_type="INDUSTRIAL",
        noi_cents=120_000_000,
        noi_growth_bps=200,
        book_value_cents=1_500_000_000,
        guidance_price_cents=1_800_000_000,
        loan_balance_cents=800_000_000,
        loan_rate_bps=550,
        loan_maturity_date="2029-12-31T00:00:00Z",
        monthly_debt_service_cents=5_500_000,
        remaining_term_months=46,
        prepayment_type="STEP_DOWN",
        defeasance_allowed=False,
    )
    payload.update(overrides)
    return payload


def gamma_asset_payload(**overrides) -> dict:
    """Unlevered multifamily asset with round-number valuation inputs
    (noi 100,000,000 at cap 500bps -> direct-cap hold value 2,000,000,000)."""
    payload = create_asset_payload(
        name="Gamma",
        market="Denver",
        asset_type="MULTIFAMILY",
        noi_cents=100_000_000,
        noi_growth_bps=200,
        book_value_cents=1_500_000_000,
        guidance_price_cents=2_000_000_000,
    )
    payload.update(overrides)
    return payload


def beta_asset_payload(**overrides) -> dict:
    """Leveraged office asset whose prepayment lockout runs to 2027-01-01."""
    payload = create_asset_payload(
        name="Beta",
        market="Chicago",
        asset_type="OFFICE",
        noi_cents=180_000_000,
        noi_growth_bps=200,
        book_value_cents=2_500_000_000,
        guidance_price_cents=3_000_000_000,
        loan_balance_cents=1_500_000_000,
        loan_rate_bps=700,
        loan_maturity_date="2031-01-01T00:00:00Z",
        monthly_debt_service_cents=11_000_000,
        remaining_term_months=50,
        prepayment_type="YIELD_MAINTENANCE",
        prepayment_lockout_until="2027-01-01T00:00:00Z",
        defeasance_allowed=True,
        defeasance_fee_cents=50_000_000,
    )
    payload.update(overrides)
    return payload


def cheap_asset_payload(**overrides) -> dict:
    """Low-price unlevered retail asset (guidance 300,000,000)."""
    payload = create_asset_payload(
        name="Cheap",
        market="Tulsa",
        asset_type="RETAIL",
        noi_cents=15_000_000,
        noi_growth_bps=100,
        book_value_cents=250_000_000,
        guidance_price_cents=300_000_000,
    )
    payload.update(overrides)
    return payload


def edge_asset_payload(name="Edge", **overrides) -> dict:
    """Unlevered retail asset priced at the first commission tier cap."""
    payload = create_asset_payload(
        name=name,
        market="Tulsa",
        asset_type="RETAIL",
        noi_cents=75_000_000,
        noi_growth_bps=100,
        book_value_cents=1_200_000_000,
        guidance_price_cents=1_500_000_000,
    )
    payload.update(overrides)
    return payload


def retail_pair_payload(name, **overrides) -> dict:
    """Unlevered retail asset used by the two-convention proration pair."""
    payload = create_asset_payload(
        name=name,
        market="Austin",
        asset_type="RETAIL",
        noi_cents=100_000_000,
        noi_growth_bps=200,
        book_value_cents=1_500_000_000,
        guidance_price_cents=2_000_000_000,
    )
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Hold/sell analyses
# ---------------------------------------------------------------------------

def create_analysis_payload(asset_id, expected_asset_version, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "expected_asset_version": expected_asset_version,
        "cap_rate_bps": 550,
        "discount_rate_bps": 800,
        "exit_cap_rate_bps": 600,
        "hold_years": 5,
        "selected_method": "DIRECT_CAP",
        "est_sale_price_cents": 5_200_000_000,
        "est_selling_costs_cents": 200_000_000,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Broker engagements
# ---------------------------------------------------------------------------

def create_engagement_payload(asset_id, window_start, window_end, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "broker_firm_name": "BrokerCo",
        "broker_user_id": "broker-1",
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Offering packages
# ---------------------------------------------------------------------------

def create_package_payload(asset_id, **overrides) -> dict:
    defaults = {"asset_id": asset_id}
    defaults.update(overrides)
    return defaults


def upload_documents_payload(categories) -> dict:
    return {
        "documents": [
            {"category": cat, "file_name": f"{cat.lower()}.pdf"} for cat in categories
        ]
    }


# ---------------------------------------------------------------------------
# Bidders and bids
# ---------------------------------------------------------------------------

def create_bidder_payload(asset_id, proof_of_funds_cents, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "organization_name": "BuyerCo",
        "proof_of_funds_cents": proof_of_funds_cents,
    }
    defaults.update(overrides)
    return defaults


def create_bid_payload(asset_id, bidder_id, price_cents, deposit_cents,
                       dd_period_days=30, closing_period_days=45, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "bidder_id": bidder_id,
        "price_cents": price_cents,
        "deposit_cents": deposit_cents,
        "dd_period_days": dd_period_days,
        "closing_period_days": closing_period_days,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Purchase agreements
# ---------------------------------------------------------------------------

def create_psa_payload(asset_id, bid_id, expected_asset_version,
                       proration_convention="ACTUAL_365", **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "bid_id": bid_id,
        "proration_convention": proration_convention,
        "expected_asset_version": expected_asset_version,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Due-diligence items
# ---------------------------------------------------------------------------

def create_dd_item_payload(psa_id, requested_reduction_cents, category="PHYSICAL",
                           description="finding", **overrides) -> dict:
    defaults = {
        "psa_id": psa_id,
        "category": category,
        "description": description,
        "requested_reduction_cents": requested_reduction_cents,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Loan payoffs
# ---------------------------------------------------------------------------

def create_payoff_payload(asset_id, method="PAYOFF", reinvestment_rate_bps=400,
                          accrued_days=12,
                          anticipated_settlement_date="2026-10-30T00:00:00Z",
                          **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "method": method,
        "reinvestment_rate_bps": reinvestment_rate_bps,
        "accrued_days": accrued_days,
        "anticipated_settlement_date": anticipated_settlement_date,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Closing statements
# ---------------------------------------------------------------------------

def create_statement_payload(psa_id, property_tax_annual_cents=0,
                             tax_period_start="2026-01-01T00:00:00Z",
                             rent_monthly_cents=0, cam_annual_cents=0,
                             **overrides) -> dict:
    defaults = {
        "psa_id": psa_id,
        "property_tax_annual_cents": property_tax_annual_cents,
        "tax_period_start": tax_period_start,
        "rent_monthly_cents": rent_monthly_cents,
        "cam_annual_cents": cam_annual_cents,
    }
    defaults.update(overrides)
    return defaults
