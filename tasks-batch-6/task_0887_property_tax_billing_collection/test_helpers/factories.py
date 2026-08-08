"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Every factory accepts **overrides so tests can pin
the specific values a claim asserts.
"""
from .constants import STANDARD_YEAR, STANDARD_MILLAGE, FIRST_DUE, SECOND_DUE

DEFAULTS = {
    "OWNER_NAME": "Test Owner",
    "SITUS_ADDRESS": "1 Test St",
    "ASSESSED_VALUE_CENTS": 20000000,   # gross 400000 at millage 20.0
    "PROPERTY_CLASS": "RESIDENTIAL",
    "ESCROW_NAME": "Test Servicing Co",
    "CLAIMED_AMOUNT_CENTS": 50000,
    "EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "EFFECTIVE_TO": "2026-12-31T00:00:00Z",
}


def create_tax_year_payload(**overrides) -> dict:
    payload = {
        "year": STANDARD_YEAR,
        "millage_rate": STANDARD_MILLAGE,
        "first_installment_due_date": FIRST_DUE,
        "second_installment_due_date": SECOND_DUE,
    }
    payload.update(overrides)
    return payload


def create_escrow_agent_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["ESCROW_NAME"],
        "servicer_code": "SVC-1",
    }
    payload.update(overrides)
    return payload


def create_parcel_payload(**overrides) -> dict:
    payload = {
        "parcel_number": "APN-1",
        "owner_name": DEFAULTS["OWNER_NAME"],
        "situs_address": DEFAULTS["SITUS_ADDRESS"],
        "assessed_value_cents": DEFAULTS["ASSESSED_VALUE_CENTS"],
        "property_class": DEFAULTS["PROPERTY_CLASS"],
    }
    payload.update(overrides)
    return payload


def create_tax_bill_payload(parcel_id, tax_year_id, **overrides) -> dict:
    payload = {"parcel_id": parcel_id, "tax_year_id": tax_year_id}
    payload.update(overrides)
    return payload


def create_relief_application_payload(parcel_id, tax_year_id, relief_class, relief_type,
                                      claimed_amount_cents=None, **overrides) -> dict:
    payload = {
        "parcel_id": parcel_id,
        "tax_year_id": tax_year_id,
        "relief_class": relief_class,
        "relief_type": relief_type,
        "claimed_amount_cents": claimed_amount_cents
        if claimed_amount_cents is not None else DEFAULTS["CLAIMED_AMOUNT_CENTS"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["EFFECTIVE_TO"],
    }
    payload.update(overrides)
    return payload


def create_payment_payload(bill_id, amount_cents, tender_type="CHECK",
                           source="COUNTER", **overrides) -> dict:
    payload = {
        "bill_id": bill_id,
        "amount_cents": amount_cents,
        "tender_type": tender_type,
        "source": source,
    }
    payload.update(overrides)
    return payload


def create_refund_payload(bill_id, amount_cents, expected_bill_version,
                          mode="GROSS_OVERPAYMENT", **overrides) -> dict:
    payload = {
        "bill_id": bill_id,
        "amount_cents": amount_cents,
        "mode": mode,
        "expected_bill_version": expected_bill_version,
    }
    payload.update(overrides)
    return payload


def create_referral_payload(bill_id, expected_bill_version, **overrides) -> dict:
    payload = {"bill_id": bill_id, "expected_bill_version": expected_bill_version}
    payload.update(overrides)
    return payload


def decide_payload(decision, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def sell_payload(sale_price_cents=None, **overrides) -> dict:
    payload = {}
    if sale_price_cents is not None:
        payload["sale_price_cents"] = sale_price_cents
    payload.update(overrides)
    return payload
