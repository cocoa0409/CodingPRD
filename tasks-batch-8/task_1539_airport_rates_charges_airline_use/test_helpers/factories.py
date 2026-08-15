"""Payload factories — one per creatable resource, input fields only."""

from .constants import DEFAULT_ACTIVITY_DATE


def create_fiscal_year_payload(**overrides) -> dict:
    defaults = {
        "year_label": "FY2027",
        "methodology": "RESIDUAL",
        "airfield_opex_cents": 1000000,
        "terminal_opex_cents": 0,
        "nonairline_airfield_revenue_cents": 0,
        "nonairline_terminal_revenue_cents": 0,
        "terminal_total_space_sqft": 100000,
        "forecast_landed_weight_kg": 1000,
        "prior_year_surplus_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_airline_payload(**overrides) -> dict:
    defaults = {
        "iata_code": "TA",
        "legal_name": "Test Air",
        "carrier_class": "PASSENGER",
        "pfc_approved": False,
    }
    defaults.update(overrides)
    return defaults


def create_airline_agreement_payload(airline_id, fiscal_year_id,
                                     **overrides) -> dict:
    defaults = {
        "airline_id": airline_id,
        "fiscal_year_id": fiscal_year_id,
        "rented_space_sqft": 0,
    }
    defaults.update(overrides)
    return defaults


def create_rates_setting_payload(expected_fiscal_year_version) -> dict:
    return {"expected_fiscal_year_version": expected_fiscal_year_version}


def create_comment_payload(airline_id, body="consultation comment") -> dict:
    return {"airline_id": airline_id, "body": body}


def create_activity_record_payload(airline_id, **overrides) -> dict:
    defaults = {
        "airline_id": airline_id,
        "activity_date": DEFAULT_ACTIVITY_DATE,
        "landed_weight_kg": 1000,
        "signature_status_at_activity": "SIGNATORY",
    }
    defaults.update(overrides)
    return defaults


def create_capital_project_payload(**overrides) -> dict:
    defaults = {
        "project_name": "Runway Rehab",
        "cost_center": "AIRFIELD",
        "budget_cents": 5000000,
        "mii_threshold_pct": 50,
    }
    defaults.update(overrides)
    return defaults


def cast_vote_payload(airline_id, ballot="APPROVE") -> dict:
    return {"airline_id": airline_id, "ballot": ballot}


def dispute_payload(airline_id, reason="disputing the true-up") -> dict:
    return {"airline_id": airline_id, "reason": reason}


def resolve_payload(override_true_up_cents=None) -> dict:
    payload: dict = {}
    if override_true_up_cents is not None:
        payload["override_true_up_cents"] = override_true_up_cents
    return payload


def recompute_payload(expected_annual_settlement_version) -> dict:
    return {
        "expected_annual_settlement_version": expected_annual_settlement_version,
    }


def record_payment_payload(outcome="PAID") -> dict:
    return {"outcome": outcome}


def create_pfc_application_payload(airline_id, **overrides) -> dict:
    defaults = {
        "airline_id": airline_id,
        "enplaned_passengers": 100,
    }
    defaults.update(overrides)
    return defaults


def decide_pfc_payload(decision="ACCEPT", rejection_reason=None) -> dict:
    payload: dict = {"decision": decision}
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    return payload
