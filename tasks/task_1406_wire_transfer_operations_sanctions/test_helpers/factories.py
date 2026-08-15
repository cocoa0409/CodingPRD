"""Payload factories — one per entity, input fields only (PRD §3).

account_number values must be unique across all accounts (PRD §3.1), so the
account factory mints a unique number per call unless overridden.
"""
import itertools

_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


def create_customer_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "legal_name": f"Test Customer {n}",
        "risk_rating": "MEDIUM",
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(customer_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "customer_id": customer_id,
        "account_number": f"A-{n:06d}",
        "daily_outgoing_limit_cents": 250000000,
    }
    defaults.update(overrides)
    return defaults


def create_beneficiary_payload(customer_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "customer_id": customer_id,
        "name": f"Beneficiary {n}",
        "bank_name": f"Bank {n}",
        "account_number": f"B-{n:06d}",
        "country_code": "US",
    }
    defaults.update(overrides)
    return defaults


def create_business_date_payload(business_date, **overrides) -> dict:
    defaults = {"business_date": business_date}
    defaults.update(overrides)
    return defaults


def create_wire_payload(ordering_account_id, beneficiary_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "ordering_account_id": ordering_account_id,
        "beneficiary_id": beneficiary_id,
        "amount_cents": 100000,
        "method": "Fedwire",
        "purpose": f"test payment {n}",
    }
    defaults.update(overrides)
    return defaults


def submit_wire_payload(business_date, **overrides) -> dict:
    defaults = {"business_date": business_date}
    defaults.update(overrides)
    return defaults


def approve_wire_payload(expected_wire_version, **overrides) -> dict:
    defaults = {"expected_wire_version": expected_wire_version}
    defaults.update(overrides)
    return defaults


def reject_wire_payload(reason="not approved", **overrides) -> dict:
    defaults = {"reason": reason}
    defaults.update(overrides)
    return defaults


def repair_wire_payload(expected_wire_version, **overrides) -> dict:
    defaults = {"expected_wire_version": expected_wire_version}
    defaults.update(overrides)
    return defaults


def record_callback_payload(outcome="CONFIRMED", **overrides) -> dict:
    defaults = {
        "outcome": outcome,
        "contact_name": "Treasury Contact",
        "contact_phone": "+1-555-0100",
    }
    defaults.update(overrides)
    return defaults


def simulate_hit_payload(wire_id, **overrides) -> dict:
    defaults = {
        "wire_id": wire_id,
        "matched_list": "INTERNAL_WATCH",
        "matched_party": "Screened Party",
        "match_score": 80,
    }
    defaults.update(overrides)
    return defaults


def hit_disposition_payload(rationale="reviewed", **overrides) -> dict:
    defaults = {"rationale": rationale}
    defaults.update(overrides)
    return defaults


def place_fraud_hold_payload(**overrides) -> dict:
    defaults = {
        "reason_code": "VELOCITY",
        "note": "analyst review",
    }
    defaults.update(overrides)
    return defaults


def confirm_fraud_hold_payload(confirmation="LEGITIMATE", **overrides) -> dict:
    defaults = {"confirmation": confirmation}
    defaults.update(overrides)
    return defaults


def create_recall_payload(wire_id, **overrides) -> dict:
    defaults = {
        "wire_id": wire_id,
        "reason": "ERROR_AMOUNT",
        "amount_to_recall_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def respond_recall_payload(response="FUNDS_RETURNED", **overrides) -> dict:
    defaults = {"response": response}
    defaults.update(overrides)
    return defaults


def post_charge_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "correspondent_name": f"Correspondent {n}",
        "charge_type": "OUR",
        "amount_cents": 1000,
        "source": "PROVISIONAL_ESTIMATE",
    }
    defaults.update(overrides)
    return defaults


def assess_fee_payload(kind="PROVISIONAL", **overrides) -> dict:
    defaults = {"kind": kind}
    defaults.update(overrides)
    return defaults


def create_investigation_payload(wire_id, **overrides) -> dict:
    defaults = {
        "wire_id": wire_id,
        "type": "TRACER",
        "note": "investigation note",
    }
    defaults.update(overrides)
    return defaults


def tracer_payload(body="tracer message", **overrides) -> dict:
    defaults = {"body": body}
    defaults.update(overrides)
    return defaults
