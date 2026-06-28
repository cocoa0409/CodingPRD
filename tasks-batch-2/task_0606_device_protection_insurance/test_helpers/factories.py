"""Payload factories — one per entity, input fields only."""
from . import constants as C


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Customer",
        "carrier_account_number": "CA-TEST-1",
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(**overrides) -> dict:
    defaults = dict(C.PLAN_STD)
    defaults.update(overrides)
    return defaults


def create_replacement_sku_payload(**overrides) -> dict:
    defaults = dict(C.SKU_BOOK)
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(customer_id, plan_id, replacement_sku_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "plan_id": plan_id,
        "imei": C.IMEI_A,
        "device_model": "PhoneA",
        "device_purchase_date": C.PURCHASE_DATE,
        "replacement_sku_id": replacement_sku_id,
    }
    defaults.update(overrides)
    return defaults


def create_premium_invoice_payload(enrollment_id, cycle_index=0, **overrides) -> dict:
    defaults = {"enrollment_id": enrollment_id, "cycle_index": cycle_index}
    defaults.update(overrides)
    return defaults


def create_claim_payload(enrollment_id, peril="CRACKED", incident_at="2026-05-10T00:00:00Z", **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "peril": peril,
        "incident_at": incident_at,
    }
    defaults.update(overrides)
    return defaults


def create_trade_in_payload(advanced_exchange_id, condition_grade="A", **overrides) -> dict:
    defaults = {
        "advanced_exchange_id": advanced_exchange_id,
        "condition_grade": condition_grade,
    }
    defaults.update(overrides)
    return defaults
