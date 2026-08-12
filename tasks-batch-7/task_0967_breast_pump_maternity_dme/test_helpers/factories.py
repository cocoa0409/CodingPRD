"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "MEMBER_NAME": "Test Member",
    "MEMBER_EMAIL": "member@example.com",
    "MEMBER_DOB": "1990-01-01",
    "MEMBER_ADDRESS": "1 Main St",
    "PAYER_NAME": "PayerX",
    "PLAN_TYPE": "COMMERCIAL_PPO",
    "BENEFIT_START": "2026-01-01",
    "BENEFIT_END": "2027-01-01",
    "DIAGNOSIS_CODE": "Z39.1",
    "PUMP_TYPE": "DOUBLE_ELECTRIC",
    "ISSUED_DATE": "2026-04-15",
    "EXPIRATION_DATE": "2026-10-01",
    "PUMP_NAME": "StdPump",
    "PUMP_PRICE": 30000,
    "WARRANTY_MONTHS": 12,
    "CARRIER": "UPS",
}


def create_member_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["MEMBER_NAME"],
        "email": DEFAULTS["MEMBER_EMAIL"],
        "date_of_birth": DEFAULTS["MEMBER_DOB"],
        "shipping_address": DEFAULTS["MEMBER_ADDRESS"],
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(member_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "payer_name": DEFAULTS["PAYER_NAME"],
        "plan_type": DEFAULTS["PLAN_TYPE"],
        "benefit_period_start": DEFAULTS["BENEFIT_START"],
        "benefit_period_end": DEFAULTS["BENEFIT_END"],
    }
    defaults.update(overrides)
    return defaults


def create_prescription_payload(member_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "diagnosis_code": DEFAULTS["DIAGNOSIS_CODE"],
        "pump_type": DEFAULTS["PUMP_TYPE"],
        "issued_date": DEFAULTS["ISSUED_DATE"],
        "expiration_date": DEFAULTS["EXPIRATION_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_pump_item_payload(**overrides) -> dict:
    defaults = {
        "item_type": "PUMP",
        "name": DEFAULTS["PUMP_NAME"],
        "sku": "PUMP-STD",
        "unit_price_cents": DEFAULTS["PUMP_PRICE"],
        "insurance_tier": "STANDARD",
        "pump_type": DEFAULTS["PUMP_TYPE"],
        "warranty_months": DEFAULTS["WARRANTY_MONTHS"],
    }
    defaults.update(overrides)
    return defaults


def create_part_item_payload(**overrides) -> dict:
    defaults = {
        "item_type": "PART",
        "name": "Valve",
        "sku": "PART-VALVE",
        "unit_price_cents": 500,
        "covered_under_resupply": True,
        "max_qty_per_frequency": 4,
    }
    defaults.update(overrides)
    return defaults


def create_garment_item_payload(**overrides) -> dict:
    defaults = {
        "item_type": "COMPRESSION_GARMENT",
        "name": "GarmentA",
        "sku": "GAR-A",
        "unit_price_cents": 6000,
    }
    defaults.update(overrides)
    return defaults


def create_pump_order_payload(member_id, policy_id, prescription_id, pump_item_id,
                              **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "policy_id": policy_id,
        "prescription_id": prescription_id,
        "pump_item_id": pump_item_id,
        "shipping_address": DEFAULTS["MEMBER_ADDRESS"],
    }
    defaults.update(overrides)
    return defaults


def create_order_line_payload(catalog_item_id: str, **overrides) -> dict:
    defaults = {"catalog_item_id": catalog_item_id, "quantity": 1}
    defaults.update(overrides)
    return defaults


def create_shipment_payload(**overrides) -> dict:
    defaults = {"carrier": DEFAULTS["CARRIER"], "tracking_number": "1Z-1"}
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    return dict(overrides)


def remit_claim_payload(outcome, adjudicated_allowed_cents, insurance_paid_cents,
                        **overrides) -> dict:
    defaults = {
        "outcome": outcome,
        "adjudicated_allowed_cents": adjudicated_allowed_cents,
        "insurance_paid_cents": insurance_paid_cents,
    }
    defaults.update(overrides)
    return defaults


def create_resupply_order_payload(schedule_id, member_id, quantity=1, **overrides) -> dict:
    defaults = {"schedule_id": schedule_id, "member_id": member_id, "quantity": quantity}
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(pump_order_id, serial_number="SN-1",
                                  issue_type="MOTOR_FAILURE", **overrides) -> dict:
    defaults = {
        "pump_order_id": pump_order_id,
        "serial_number": serial_number,
        "issue_type": issue_type,
    }
    defaults.update(overrides)
    return defaults


def payer_decision_payload(decision, **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults
