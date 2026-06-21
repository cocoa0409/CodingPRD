"""Payload factories — one per entity, input fields only.

Field names mirror the PRD exactly. Optional fields (fuel_surcharge_pct on a
contract rate, invoiced_accessorial_codes on a freight invoice) are omitted from
the default payloads unless explicitly supplied as an override.
"""


def create_carrier_payload(**overrides) -> dict:
    defaults = {"name": "Acme TL", "scac": "ACME", "mode": "TL"}
    defaults.update(overrides)
    return defaults


def create_contract_rate_payload(**overrides) -> dict:
    defaults = {
        "carrier_id": None,
        "mode": "TL",
        "origin_zone": "Z1",
        "dest_zone": "Z2",
        "base_rate_per_mile_cents": 250,
        "min_charge_cents": 50000,
        "fuel_surcharge_pct": 0.15,
        "effective_start_minute": 0,
        "effective_end_minute": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(**overrides) -> dict:
    defaults = {
        "customer_ref": "C1",
        "origin_zone": "Z1",
        "dest_zone": "Z2",
        "weight_lbs": 10000,
        "declared_value_cents": 200000,
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(**overrides) -> dict:
    defaults = {
        "order_id": None,
        "mode": "TL",
        "distance_miles": 300,
        "weight_lbs": 6000,
        "promised_eta_minute": 500,
    }
    defaults.update(overrides)
    return defaults


def create_tender_payload(**overrides) -> dict:
    defaults = {"tender_minute": 100}
    defaults.update(overrides)
    return defaults


def create_load_payload(**overrides) -> dict:
    defaults = {"carrier_id": None, "planned_capacity_lbs": 10000}
    defaults.update(overrides)
    return defaults


def add_shipment_to_load_payload(**overrides) -> dict:
    defaults = {"shipment_id": None, "expected_load_version": None}
    defaults.update(overrides)
    return defaults


def create_dock_appointment_payload(**overrides) -> dict:
    defaults = {
        "load_id": None,
        "dock_door": "D1",
        "start_minute": 200,
        "end_minute": 260,
    }
    defaults.update(overrides)
    return defaults


def create_freight_invoice_payload(**overrides) -> dict:
    defaults = {
        "shipment_id": None,
        "invoiced_linehaul_cents": 86250,
    }
    defaults.update(overrides)
    return defaults


def deliver_shipment_payload(**overrides) -> dict:
    defaults = {"delivered_minute": 400}
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    defaults = {
        "shipment_id": None,
        "claim_type": "DAMAGE",
        "claimed_amount_cents": 50000,
    }
    defaults.update(overrides)
    return defaults
