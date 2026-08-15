"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import INVOICE_DATE, RUN_DATE, SHIP_DATE


def create_client_payload(**overrides) -> dict:
    defaults = {"name": "Acme Shippers", "home_country": "US", "home_currency": "USD"}
    defaults.update(overrides)
    return defaults


def create_carrier_payload(**overrides) -> dict:
    defaults = {
        "scac_code": "CARR",
        "legal_name": "Carrier One",
        "country": "US",
        "billing_currency": "USD",
        "payment_terms_days": 14,
        "remit_email": "remit@carr.example",
    }
    defaults.update(overrides)
    return defaults


def ltl_lane_us_ca(**overrides) -> dict:
    """Canonical LTL lane: 150/kg from 0 kg, 10% fuel, LIFTGATE 5000 flat
    under a 20% cap, 20000 minimum charge."""
    lane = {
        "origin_country": "US",
        "dest_country": "CA",
        "mode": "LTL",
        "weight_breaks": [{"min_kg": 0, "rate_per_kg_minor": 150}],
        "fuel_surcharge_pct_bp": 1000,
        "accessorials": [{"code": "LIFTGATE", "flat_minor": 5000, "cap_pct_bp": 2000}],
        "minimum_charge_minor": 20000,
    }
    lane.update(overrides)
    return lane


def parcel_lane_de_us(**overrides) -> dict:
    """EUR PARCEL lane: 333/kg, no fuel, DETENTION/STORAGE 333 flat cap 100%."""
    lane = {
        "origin_country": "DE",
        "dest_country": "US",
        "mode": "PARCEL",
        "weight_breaks": [{"min_kg": 0, "rate_per_kg_minor": 333}],
        "fuel_surcharge_pct_bp": 0,
        "accessorials": [
            {"code": "DETENTION", "flat_minor": 333, "cap_pct_bp": 10000},
            {"code": "STORAGE", "flat_minor": 333, "cap_pct_bp": 10000},
        ],
        "minimum_charge_minor": 0,
    }
    lane.update(overrides)
    return lane


def ftl_lane_us_us(**overrides) -> dict:
    """USD FTL lane: 101/kg, no fuel, no accessorials, no minimum."""
    lane = {
        "origin_country": "US",
        "dest_country": "US",
        "mode": "FTL",
        "weight_breaks": [{"min_kg": 0, "rate_per_kg_minor": 101}],
        "fuel_surcharge_pct_bp": 0,
        "accessorials": [],
        "minimum_charge_minor": 0,
    }
    lane.update(overrides)
    return lane


def create_rate_contract_payload(lanes=None, **overrides) -> dict:
    defaults = {
        "name": "C1",
        "currency": "USD",
        "lanes": lanes if lanes is not None else [ltl_lane_us_ca()],
        "effective_from": "2026-08-01",
        "effective_to": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(carrier_id, **overrides) -> dict:
    defaults = {
        "carrier_id": carrier_id,
        "pro_number": "PRO-1001",
        "ship_date": SHIP_DATE,
        "origin_country": "US",
        "dest_country": "CA",
        "mode": "LTL",
        "actual_weight_kg": 500,
        "accessorials_rendered": ["LIFTGATE"],
    }
    defaults.update(overrides)
    return defaults


def standard_ltl_lines() -> list:
    """Lines billing exactly the canonical rated outcome (total 87500)."""
    return [
        {"charge_code": "BASE_FREIGHT", "billed_amount_minor": 75000},
        {"charge_code": "FUEL_SURCHARGE", "billed_amount_minor": 7500},
        {"charge_code": "LIFTGATE", "billed_amount_minor": 5000},
    ]


def create_invoice_payload(carrier_id, **overrides) -> dict:
    lines = overrides.pop("lines", standard_ltl_lines())
    billed = overrides.pop(
        "billed_total_minor", sum(line["billed_amount_minor"] for line in lines)
    )
    defaults = {
        "carrier_id": carrier_id,
        "invoice_number": "INV-0001",
        "invoice_date": INVOICE_DATE,
        "currency": "USD",
        "billed_total_minor": billed,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_gl_account_payload(**overrides) -> dict:
    defaults = {"code": "4000", "business_unit": "BU-NORTH", "country": "US"}
    defaults.update(overrides)
    return defaults


def create_fx_rate_payload(**overrides) -> dict:
    defaults = {
        "from_currency": "EUR",
        "to_currency": "USD",
        "effective_date": "2026-08-01",
        "rate_ppm": 1_100_000,
        "source": "ECB",
    }
    defaults.update(overrides)
    return defaults


def create_payment_run_payload(**overrides) -> dict:
    defaults = {"run_date": RUN_DATE, "currency": "USD"}
    defaults.update(overrides)
    return defaults


def create_recovery_claim_payload(**overrides) -> dict:
    defaults = {"claimed_amount_minor": 2000, "channel": "CREDIT_MEMO"}
    defaults.update(overrides)
    return defaults


def create_analytics_export_payload(**overrides) -> dict:
    defaults = {"date_from": "2026-08-01", "date_to": "2026-08-31"}
    defaults.update(overrides)
    return defaults
