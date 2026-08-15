"""Payload factories — one per creatable resource, input fields only."""
import itertools

from .constants import (
    CASE_EXPIRY,
    HIGH_CREDIT_LIMIT,
    LICENSE_VALID_FROM,
    LICENSE_VALID_TO,
)

# Unique-value generators so parallel tests never collide on natural keys.
_ndc_counter = itertools.count(1)
_sscc_counter = itertools.count(1)
_sni_counter = itertools.count(1)
_license_counter = itertools.count(1)
_partner_counter = itertools.count(1)


def _next_ndc() -> str:
    return f"{next(_ndc_counter):011d}"


def create_trading_partner_payload(**overrides) -> dict:
    n = next(_partner_counter)
    defaults = {
        "partner_name": f"Partner-{n}",
        "partner_kind": "CUSTOMER",
        "dea_number": f"AC{n:07d}",
        "credit_limit_cents": HIGH_CREDIT_LIMIT,
    }
    defaults.update(overrides)
    return defaults


def create_license_payload(partner_id: str, **overrides) -> dict:
    n = next(_license_counter)
    defaults = {
        "partner_id": partner_id,
        "state_code": "CA",
        "license_number": f"LIC-{n:05d}",
        "license_scope": "FULL",
        "valid_from": LICENSE_VALID_FROM,
        "valid_to": LICENSE_VALID_TO,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    n = next(_license_counter)
    defaults = {
        "ndc": _next_ndc(),
        "product_name": f"Product-{n}",
        "is_controlled": False,
        "is_cold_chain": False,
        "wholesale_acquisition_cost_cents": 1000,
        "is_340b_contracted": False,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_policy_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "pool_units": 10,
        "policy_mode": "PRO_RATA",
        "min_guarantee_units": 0,
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(product_id: str, **overrides) -> dict:
    n = next(_sscc_counter)
    defaults = {
        "sscc": f"SSCC-{n:06d}",
        "product_id": product_id,
        "lot_number": f"LOT-{n:05d}",
        "expiry_date": CASE_EXPIRY,
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(case_id: str, **overrides) -> dict:
    n = next(_sni_counter)
    defaults = {
        "sni": f"SNI-{n:06d}",
        "case_id": case_id,
    }
    defaults.update(overrides)
    return defaults


def create_epcis_event_payload(subject_case_id: str, sender_id: str, recipient_id: str,
                               **overrides) -> dict:
    defaults = {
        "event_type": "SHIP",
        "subject_case_id": subject_case_id,
        "event_time": "2026-08-01T00:00:00Z",
        "sender_partner_id": sender_id,
        "recipient_partner_id": recipient_id,
    }
    defaults.update(overrides)
    return defaults


def create_purchase_order_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "ship_to_state": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_order_line_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "quantity_requested": 1,
    }
    defaults.update(overrides)
    return defaults


def create_investigation_payload(case_id: str, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "opened_reason": "suspect product flagged for verification",
    }
    defaults.update(overrides)
    return defaults


def create_chargeback_claim_payload(order_id: str, claimed_amount_cents: int, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "claimed_amount_cents": claimed_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_return_authorization_payload(order_id: str, product_id: str, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "product_id": product_id,
        "quantity_returned": 1,
    }
    defaults.update(overrides)
    return defaults
