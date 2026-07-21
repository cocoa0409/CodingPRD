"""Payload factories — one per entity, input fields only (PRD Section 3).

A module-level sequence keeps default serials/emails unique within a single
test run so a fixture can mint several customers or watches without collision.
"""
import itertools

_seq = itertools.count(1)


def _next() -> int:
    return next(_seq)


def create_customer_payload(**overrides) -> dict:
    n = _next()
    defaults = {"full_name": f"Test Client {n}", "email": f"client{n}@example.com"}
    defaults.update(overrides)
    return defaults


def create_watch_model_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "brand": "Rolex",
        "reference_number": f"REF-{n}",
        "display_name": f"Model {n}",
        "msrp_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults


def create_watchmaker_payload(**overrides) -> dict:
    n = _next()
    defaults = {"display_name": f"Bench {n}"}
    defaults.update(overrides)
    return defaults


def create_watch_payload(model_id: str, **overrides) -> dict:
    n = _next()
    defaults = {
        "model_id": model_id,
        "serial_number": f"SER-{n}",
        "condition_grade": "NEW",
        "list_price_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults


def create_waitlist_entry_payload(customer_id: str, model_id: str, **overrides) -> dict:
    defaults = {"customer_id": customer_id, "model_id": model_id}
    defaults.update(overrides)
    return defaults


def create_service_ticket_payload(
    watch_id: str, customer_id: str, watchmaker_id: str, **overrides
) -> dict:
    defaults = {
        "watch_id": watch_id,
        "customer_id": customer_id,
        "watchmaker_id": watchmaker_id,
        "service_type": "BATTERY",
        "appt_start": "2026-07-03T09:00:00Z",
        "appt_end": "2026-07-03T09:30:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_appraisal_payload(
    purpose: str, valuation_basis: str, expected_watch_version: int, **overrides
) -> dict:
    defaults = {
        "purpose": purpose,
        "valuation_basis": valuation_basis,
        "expected_watch_version": expected_watch_version,
    }
    defaults.update(overrides)
    return defaults


def create_trade_in_offer_payload(customer_id: str, disposition: str, **overrides) -> dict:
    n = _next()
    defaults = {
        "customer_id": customer_id,
        "incoming_brand": "Rolex",
        "incoming_reference": "126610LN",
        "serial_number": f"TI-{n}",
        "est_model_msrp_cents": 1000000,
        "condition_grade": "EXCELLENT",
        "disposition": disposition,
    }
    defaults.update(overrides)
    return defaults


def create_layaway_plan_payload(
    customer_id: str, watch_id: str, deposit_cents: int, term_months: int,
    first_due_at: str, **overrides
) -> dict:
    defaults = {
        "customer_id": customer_id,
        "watch_id": watch_id,
        "deposit_cents": deposit_cents,
        "term_months": term_months,
        "first_due_at": first_due_at,
    }
    defaults.update(overrides)
    return defaults
