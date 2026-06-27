"""Payload factories — one per entity, input fields only.

Each factory provides PRD-valid defaults for the required input fields and
accepts **overrides. Optional fields with PRD defaults (source_kind,
equity_rate_pct, equity_cap_pct, restock_fee_pct, commission_pct, deposit_pct,
parts_cost_cents, rush, rental_agreement_id, special_order_id) are omitted
unless explicitly supplied, so that default behaviour is exercised by default.
"""
import itertools

_serial_counter = itertools.count(1)
_email_counter = itertools.count(1)


def unique_serial(prefix: str = "SN") -> str:
    return f"{prefix}-{next(_serial_counter)}"


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}{next(_email_counter)}@example.com"


def create_customer_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Customer",
        "email": unique_email("customer"),
        "credit_score": 700,
    }
    payload.update(overrides)
    return payload


def create_unit_payload(**overrides) -> dict:
    payload = {
        "model_name": "Test Model",
        "category": "GUITAR",
        "condition": "NEW",
        "serial_number": unique_serial("UNIT"),
        "acquisition_cost_cents": 30000,
        "list_price_cents": 60000,
        "monthly_rent_cents": 5000,
    }
    payload.update(overrides)
    return payload


def reserve_unit_payload(customer_id: str, expected_version: int, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "expected_inventory_unit_version": expected_version,
    }
    payload.update(overrides)
    return payload


def create_agreement_payload(customer_id: str, inventory_unit_id: str,
                             plan: str = "RENTAL", **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "inventory_unit_id": inventory_unit_id,
        "plan": plan,
    }
    payload.update(overrides)
    return payload


def rent_payment_payload(billing_cycle_index: int, **overrides) -> dict:
    payload = {"billing_cycle_index": billing_cycle_index}
    payload.update(overrides)
    return payload


def advance_cycle_payload(billing_cycle_index: int, **overrides) -> dict:
    payload = {"billing_cycle_index": billing_cycle_index}
    payload.update(overrides)
    return payload


def buyout_payload(amount_cents: int, expected_agreement_version: int, **overrides) -> dict:
    payload = {
        "amount_cents": amount_cents,
        "expected_agreement_version": expected_agreement_version,
    }
    payload.update(overrides)
    return payload


def create_layaway_payload(customer_id: str, inventory_unit_id: str,
                           deposit_cents: int = 5000, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "inventory_unit_id": inventory_unit_id,
        "deposit_cents": deposit_cents,
    }
    payload.update(overrides)
    return payload


def layaway_payment_payload(amount_cents: int, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def create_ticket_payload(customer_id: str, labor_hours: float = 1.0,
                          labor_rate_cents: int = 6000, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "labor_hours": labor_hours,
        "labor_rate_cents": labor_rate_cents,
    }
    payload.update(overrides)
    return payload


def create_consignment_payload(consignor_id: str, ask_price_cents: int = 80000,
                               **overrides) -> dict:
    payload = {
        "consignor_id": consignor_id,
        "model_name": "Consigned Model",
        "ask_price_cents": ask_price_cents,
    }
    payload.update(overrides)
    return payload


def create_trade_in_payload(customer_id: str, condition: str = "USED",
                            appraised_value_cents: int = 50000, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "model_name": "Traded Model",
        "condition": condition,
        "appraised_value_cents": appraised_value_cents,
    }
    payload.update(overrides)
    return payload


def create_financing_payload(customer_id: str, principal_cents: int = 240000,
                             term_months: int = 12, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "principal_cents": principal_cents,
        "term_months": term_months,
    }
    payload.update(overrides)
    return payload


def create_special_order_payload(customer_id: str, quoted_price_cents: int = 200000,
                                 **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "model_name": "Special Model",
        "quoted_price_cents": quoted_price_cents,
    }
    payload.update(overrides)
    return payload


def pay_deposit_payload(amount_cents: int, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def receive_special_order_payload(serial_number: str = None, category: str = "GUITAR",
                                  **overrides) -> dict:
    payload = {
        "serial_number": serial_number or unique_serial("SO"),
        "category": category,
    }
    payload.update(overrides)
    return payload


def create_enrollment_payload(student_id: str, instrument_family: str = "GUITAR",
                              sessions_per_month: int = 4, base_rate_cents: int = 5000,
                              **overrides) -> dict:
    payload = {
        "student_id": student_id,
        "instrument_family": instrument_family,
        "sessions_per_month": sessions_per_month,
        "base_rate_cents": base_rate_cents,
    }
    payload.update(overrides)
    return payload
