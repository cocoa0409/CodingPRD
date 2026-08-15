"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "CLIENT_NAME": "Test Client",
    "CLIENT_RISK": 50,
    "BENCHMARK_NAME": "Test Bench",
    "OBJECTIVE_TEXT": "Growth",
    "IPS_RISK": 50,
    "REVIEW_CADENCE_MONTHS": 12,
    "PORTFOLIO_NAME": "Main",
    "TAX_STATUS": "TAXABLE",
    "TARGETS_60_40": [
        {"asset_class": "US_EQUITY", "target_pct": 60.00, "band_pct": 5.00},
        {"asset_class": "CASH_EQUIVALENT", "target_pct": 40.00, "band_pct": 5.00},
    ],
    "TARGETS_CASH_ONLY": [
        {"asset_class": "CASH_EQUIVALENT", "target_pct": 100.00, "band_pct": 50.00},
    ],
    "TARGETS_US_ONLY": [
        {"asset_class": "US_EQUITY", "target_pct": 100.00, "band_pct": 50.00},
    ],
    "TARGETS_60_20_20": [
        {"asset_class": "US_EQUITY", "target_pct": 60.00, "band_pct": 5.00},
        {"asset_class": "INTL_EQUITY", "target_pct": 20.00, "band_pct": 5.00},
        {"asset_class": "CASH_EQUIVALENT", "target_pct": 20.00, "band_pct": 5.00},
    ],
    "OCCURRED_AT": "2026-08-01T00:00:00Z",
    "MEETING_DATE": "2026-08-01",
}


def create_client_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["CLIENT_NAME"],
        "risk_tolerance_score": DEFAULTS["CLIENT_RISK"],
    }
    payload.update(overrides)
    return payload


def create_benchmark_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["BENCHMARK_NAME"],
        "description": "blend",
    }
    payload.update(overrides)
    return payload


def create_ips_payload(client_id, benchmark_id, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "benchmark_id": benchmark_id,
        "objective_text": DEFAULTS["OBJECTIVE_TEXT"],
        "risk_tolerance_score": DEFAULTS["IPS_RISK"],
        "review_cadence_months": DEFAULTS["REVIEW_CADENCE_MONTHS"],
    }
    payload.update(overrides)
    return payload


def allocation_targets_payload(targets) -> dict:
    """targets: list of {asset_class, target_pct, band_pct} dicts."""
    return {"targets": targets}


def create_portfolio_payload(client_id, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "name": DEFAULTS["PORTFOLIO_NAME"],
        "tax_status": DEFAULTS["TAX_STATUS"],
    }
    payload.update(overrides)
    return payload


def cash_movement_payload(direction, amount_cents, occurred_at=None) -> dict:
    return {
        "direction": direction,
        "amount_cents": amount_cents,
        "occurred_at": occurred_at or DEFAULTS["OCCURRED_AT"],
    }


def create_security_payload(**overrides) -> dict:
    payload = {
        "ticker": "EQA",
        "asset_class": "US_EQUITY",
        "initial_price_cents": 1000,
    }
    payload.update(overrides)
    return payload


def create_position_payload(portfolio_id, security_id, **overrides) -> dict:
    payload = {
        "portfolio_id": portfolio_id,
        "security_id": security_id,
        "quantity": 10,
        "opening_cost_basis_cents": 7000,
    }
    payload.update(overrides)
    return payload


def create_restricted_list_entry_payload(security_id, **overrides) -> dict:
    payload = {
        "security_id": security_id,
        "restriction_level": "NO_TRADE",
        "effective_from": "2026-08-01T00:00:00Z",
        "effective_to": "2026-09-01T00:00:00Z",
        "reason": "compliance hold",
    }
    payload.update(overrides)
    return payload


def create_rebalance_proposal_payload(portfolio_id, expected_portfolio_version,
                                      trigger_type="DRIFT_BREACH") -> dict:
    return {
        "portfolio_id": portfolio_id,
        "trigger_type": trigger_type,
        "expected_portfolio_version": expected_portfolio_version,
    }


def create_withdrawal_request_payload(portfolio_id, **overrides) -> dict:
    payload = {
        "portfolio_id": portfolio_id,
        "amount_cents": 150000,
        "funding_mode": "TAX_AWARE",
    }
    payload.update(overrides)
    return payload


def create_performance_report_payload(portfolio_id, benchmark_id, **overrides) -> dict:
    payload = {
        "portfolio_id": portfolio_id,
        "benchmark_id": benchmark_id,
        "period_start": "2026-08-01",
        "period_end": "2026-08-31",
        "calculation_method": "TIME_WEIGHTED",
        "beginning_value_cents": 100000,
        "ending_value_cents": 110000,
        "benchmark_return_bps": 0,
    }
    payload.update(overrides)
    return payload


def create_ips_amendment_payload(ips_id, **overrides) -> dict:
    payload = {
        "ips_id": ips_id,
        "proposed_objective_text": "Updated objective",
    }
    payload.update(overrides)
    return payload


def create_committee_minute_payload(**overrides) -> dict:
    payload = {
        "meeting_date": DEFAULTS["MEETING_DATE"],
        "amendment_refs": [],
        "decisions_text": "Quarterly review",
    }
    payload.update(overrides)
    return payload
