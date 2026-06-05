"""Payload factories — one per entity, input fields only (PRD §3)."""


def create_security_payload(
    ticker: str = "VTI",
    asset_class: str = "US_EQUITY",
    price_cents: int = 10000,
    correlated_with=None,
    **overrides,
) -> dict:
    """Security input fields (PRD §3.1). correlated_with is optional."""
    payload = {
        "ticker": ticker,
        "asset_class": asset_class,
        "price_cents": price_cents,
    }
    if correlated_with is not None:
        payload["correlated_with"] = correlated_with
    payload.update(overrides)
    return payload


def create_model_portfolio_payload(
    name: str = "Test Model",
    min_risk_score: int = 70,
    max_risk_score: int = 100,
    targets=None,
    drift_threshold_pct: int = 90,
    lot_selection: str = None,
    **overrides,
) -> dict:
    """ModelPortfolio input fields (PRD §3.1). lot_selection optional (defaults FIFO server-side)."""
    payload = {
        "name": name,
        "min_risk_score": min_risk_score,
        "max_risk_score": max_risk_score,
        "targets": targets
        if targets is not None
        else [{"asset_class": "US_EQUITY", "target_pct": 100}],
        "drift_threshold_pct": drift_threshold_pct,
    }
    if lot_selection is not None:
        payload["lot_selection"] = lot_selection
    payload.update(overrides)
    return payload


def create_account_payload(client_email: str = "client@example.com", **overrides) -> dict:
    """Account input fields (PRD §3.2)."""
    payload = {"client_email": client_email}
    payload.update(overrides)
    return payload


def create_questionnaire_payload(
    account_id: str,
    horizon_years: int = 30,
    loss_tolerance: int = 9,
    liquidity_need: int = 1,
    income_band: int = 8,
    **overrides,
) -> dict:
    """RiskQuestionnaire input fields (PRD §3.2). Default inputs score 82."""
    payload = {
        "account_id": account_id,
        "horizon_years": horizon_years,
        "loss_tolerance": loss_tolerance,
        "liquidity_need": liquidity_need,
        "income_band": income_band,
    }
    payload.update(overrides)
    return payload


def create_tax_lot_payload(
    account_id: str,
    security_id: str,
    quantity: float = 5,
    cost_basis_cents: int = 60000,
    **overrides,
) -> dict:
    """TaxLot input fields (PRD §3.3)."""
    payload = {
        "account_id": account_id,
        "security_id": security_id,
        "quantity": quantity,
        "cost_basis_cents": cost_basis_cents,
    }
    payload.update(overrides)
    return payload


def create_harvest_event_payload(
    account_id: str,
    source_lot_id: str,
    replacement_security_id: str,
    expected_account_version: int,
    **overrides,
) -> dict:
    """HarvestEvent input fields (PRD §3.4)."""
    payload = {
        "account_id": account_id,
        "source_lot_id": source_lot_id,
        "replacement_security_id": replacement_security_id,
        "expected_account_version": expected_account_version,
    }
    payload.update(overrides)
    return payload


def create_rebalance_event_payload(
    account_id: str,
    quarter_label: str,
    expected_account_version: int,
    **overrides,
) -> dict:
    """RebalanceEvent input fields (PRD §3.6)."""
    payload = {
        "account_id": account_id,
        "quarter_label": quarter_label,
        "expected_account_version": expected_account_version,
    }
    payload.update(overrides)
    return payload


def create_tax_form_payload(account_id: str, tax_year: int = 2025, **overrides) -> dict:
    """TaxForm1099B input fields (PRD §3.9)."""
    payload = {"account_id": account_id, "tax_year": tax_year}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601: str) -> dict:
    """Clock-setting input field (PRD §3.10)."""
    return {"to_iso8601": to_iso8601}
