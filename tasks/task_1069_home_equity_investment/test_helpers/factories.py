"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _uniq() -> int:
    return next(_counter)


def create_fund_payload(**overrides) -> dict:
    payload = {
        "name": f"Fund {_uniq()}",
        "total_capital_cents": 50000000,
    }
    payload.update(overrides)
    return payload


def create_homeowner_payload(**overrides) -> dict:
    n = _uniq()
    payload = {
        "email": f"homeowner{n}@example.com",
        "full_name": f"Home Owner {n}",
    }
    payload.update(overrides)
    return payload


def create_application_payload(homeowner_id, fund_id, **overrides) -> dict:
    payload = {
        "homeowner_id": homeowner_id,
        "fund_id": fund_id,
        "property_address": f"{_uniq()} Main St",
        "property_type": "SINGLE_FAMILY",
        "homeowner_estimated_value_cents": 80000000,
        "existing_mortgage_balance_cents": 40000000,
        "requested_investment_cents": 10000000,
    }
    payload.update(overrides)
    return payload


def create_avm_valuation_payload(valued_amount_cents=80000000, **overrides) -> dict:
    payload = {
        "method": "AVM",
        "valued_amount_cents": valued_amount_cents,
        "confidence_score": 0.9,
    }
    payload.update(overrides)
    return payload


def create_appraisal_valuation_payload(**overrides) -> dict:
    payload = {"method": "APPRAISAL"}
    payload.update(overrides)
    return payload


def create_appraiser_payload(**overrides) -> dict:
    payload = {
        "full_name": f"Appraiser {_uniq()}",
        "region_code": "CA-BAY",
    }
    payload.update(overrides)
    return payload


def create_appointment_payload(appraiser_id, valuation_id, **overrides) -> dict:
    payload = {
        "appraiser_id": appraiser_id,
        "valuation_id": valuation_id,
        "region_code": "CA-BAY",
        "scheduled_start": "2026-07-05T10:00:00Z",
        "scheduled_end": "2026-07-05T11:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_offer_payload(valuation_id, **overrides) -> dict:
    payload = {
        "valuation_id": valuation_id,
        "investment_amount_cents": 10000000,
        "option_percentage": 0.25,
        "risk_adjustment_pct": 0.10,
        "term_months": 120,
        "capped_annual_rate": 0.19,
        "expires_at": "2027-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_inspector_payload(**overrides) -> dict:
    payload = {
        "full_name": f"Inspector {_uniq()}",
        "region_code": "CA-BAY",
    }
    payload.update(overrides)
    return payload


def create_inspection_payload(inspector_id, scheduled_date="2026-09-01", **overrides) -> dict:
    payload = {
        "inspector_id": inspector_id,
        "scheduled_date": scheduled_date,
    }
    payload.update(overrides)
    return payload


def create_sale_settlement_payload(sale_price_cents, mortgage_payoff_cents,
                                   expected_agreement_version, **overrides) -> dict:
    payload = {
        "settlement_type": "SALE",
        "sale_price_cents": sale_price_cents,
        "mortgage_payoff_cents": mortgage_payoff_cents,
        "expected_agreement_version": expected_agreement_version,
    }
    payload.update(overrides)
    return payload


def create_buyout_settlement_payload(current_appraised_value_cents, mortgage_payoff_cents,
                                     expected_agreement_version, **overrides) -> dict:
    payload = {
        "settlement_type": "BUYOUT",
        "current_appraised_value_cents": current_appraised_value_cents,
        "mortgage_payoff_cents": mortgage_payoff_cents,
        "expected_agreement_version": expected_agreement_version,
    }
    payload.update(overrides)
    return payload
