"""Payload factories — one per entity, input fields only."""

from .constants import TEST_DEFAULTS

CARRIER_SEEDS = {
    "AA": {"iata_code": "AA", "name": "Aurora Air", "base_currency": "USD"},
    "BB": {"iata_code": "BB", "name": "Borealis Airways", "base_currency": "USD"},
    "CC": {"iata_code": "CC", "name": "Cirrus Continental", "base_currency": "USD"},
    "DD": {"iata_code": "DD", "name": "Delta Zephyr", "base_currency": "EUR"},
}


def create_carrier_payload(code="AA", **overrides):
    seed = CARRIER_SEEDS.get(code, CARRIER_SEEDS["AA"])
    payload = {
        "iata_code": seed["iata_code"],
        "name": seed["name"],
        "base_currency": seed["base_currency"],
        "credit_limit_minor": TEST_DEFAULTS["BIG_CREDIT_LIMIT"],
    }
    payload.update(overrides)
    return payload


def create_agreement_payload(issuing_carrier_id, partner_carrier_id, **overrides):
    payload = {
        "issuing_carrier_id": issuing_carrier_id,
        "partner_carrier_id": partner_carrier_id,
        "agreement_type": "SPA_FLAT",
        "settlement_currency": "USD",
        "effective_from": "2026-08-01",
        "effective_to": "2026-08-31",
    }
    payload.update(overrides)
    return payload


def create_factor_payload(origin="LHR", destination="CDG", class_of_service="ECONOMY", **overrides):
    payload = {
        "origin": origin,
        "destination": destination,
        "class_of_service": class_of_service,
    }
    payload.update(overrides)
    return payload


def create_period_payload(**overrides):
    payload = {
        "period_code": TEST_DEFAULTS["PERIOD_CODE"],
        "period_start": TEST_DEFAULTS["PERIOD_START"],
        "period_end": TEST_DEFAULTS["PERIOD_END"],
        "submission_deadline": TEST_DEFAULTS["SUBMISSION_DEADLINE"],
        "rate_fixing_date": TEST_DEFAULTS["RATE_FIXING_DATE"],
        "settlement_currency": "USD",
    }
    payload.update(overrides)
    return payload


def create_exchange_rate_payload(**overrides):
    payload = {
        "from_currency": "EUR",
        "to_currency": "USD",
        "effective_date": "2026-08-05T00:00:00Z",
        "rate_scaled": 1085000,
    }
    payload.update(overrides)
    return payload


def create_ticket_payload(validating_carrier_id, ticket_number="0100000000001", **overrides):
    payload = {
        "ticket_number": ticket_number,
        "validating_carrier_id": validating_carrier_id,
        "sale_currency": "USD",
        "total_fare_minor": TEST_DEFAULTS["DEFAULT_FARE_MINOR"],
        "issue_date": TEST_DEFAULTS["CLOCK_TRADING_DAY"],
    }
    payload.update(overrides)
    return payload


def create_coupon_payload(operating_carrier_id, coupon_number=1, **overrides):
    payload = {
        "coupon_number": coupon_number,
        "origin": "JFK",
        "destination": "LHR",
        "operating_carrier_id": operating_carrier_id,
        "class_of_service": "ECONOMY",
        "tpm_miles": TEST_DEFAULTS["DEFAULT_TPM_MILES"],
    }
    payload.update(overrides)
    return payload


def create_invoice_payload(period_id, billing_carrier_id, billed_carrier_id, coupon_ids, **overrides):
    payload = {
        "settlement_period_id": period_id,
        "billing_carrier_id": billing_carrier_id,
        "billed_carrier_id": billed_carrier_id,
        "billing_currency": "USD",
        "coupon_ids": list(coupon_ids),
    }
    payload.update(overrides)
    return payload


def create_memo_payload(invoice_id, coupon_id, expected_invoice_version, **overrides):
    payload = {
        "invoice_id": invoice_id,
        "coupon_id": coupon_id,
        "amount_minor": 10000,
        "reason_code": "PRORATE_FACTOR_DISPUTE",
        "expected_invoice_version": expected_invoice_version,
    }
    payload.update(overrides)
    return payload


def create_audit_sample_payload(
    auditing_carrier_id, audited_carrier_id, period_id, sample_coupon_ids, **overrides
):
    payload = {
        "auditing_carrier_id": auditing_carrier_id,
        "audited_carrier_id": audited_carrier_id,
        "settlement_period_id": period_id,
        "claim_currency": "USD",
        "sample_coupon_ids": list(sample_coupon_ids),
    }
    payload.update(overrides)
    return payload


def prorate_payload(run_type, expected_ticket_version):
    return {"run_type": run_type, "expected_ticket_version": expected_ticket_version}
