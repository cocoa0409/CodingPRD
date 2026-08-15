"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

from .constants import DEFAULT_WINDOW_END, DEFAULT_WINDOW_START

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter):05d}"


def customer_payload(**overrides) -> dict:
    defaults = {"legal_name": _uniq("Customer")}
    defaults.update(overrides)
    return defaults


def pricing_agreement_payload(**overrides) -> dict:
    defaults = {
        "pricing_mode": "TOLLING_FEE",
        "tolling_base_fee_cents": 100,
        "tolling_per_kg_cents": 1,
        "formulated_price_per_kg_cents": 0,
        "effective_from": DEFAULT_WINDOW_START,
        "effective_to": DEFAULT_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def lot_payload(**overrides) -> dict:
    defaults = {
        "material_code": "M-A",
        "ghS_class": "NON_HAZ",
        "quantity_kg_received": 1000,
        "storage_zone": "Z_GENERAL",
        "received_at": "2026-08-02T08:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def recipe_component(material_code="M-A", mass_fraction_pct=100.0, charge_order=1) -> dict:
    return {
        "material_code": material_code,
        "mass_fraction_pct": mass_fraction_pct,
        "charge_order": charge_order,
    }


def recipe_payload(customer_id, **overrides) -> dict:
    defaults = {
        "name": _uniq("Recipe"),
        "revision": 1,
        "customer_id": customer_id,
        "target_density_kg_per_l": 1.0,
        "theoretical_yield_pct": 100.0,
        "components": [recipe_component()],
    }
    defaults.update(overrides)
    return defaults


def tank_payload(**overrides) -> dict:
    defaults = {
        "tank_code": _uniq("TK"),
        "capacity_l": 1000,
        "working_capacity_l": 1000,
        "current_zone": "Z_GENERAL",
    }
    defaults.update(overrides)
    return defaults


def cleaning_record_payload(**overrides) -> dict:
    defaults = {
        "method": "DRY_PURGE",
        "started_at": "2026-08-02T08:00:00Z",
        "completed_at": "2026-08-02T09:00:00Z",
        "residue_ppm": 0,
    }
    defaults.update(overrides)
    return defaults


def batch_job_payload(recipe_id, pricing_agreement_id, tank_id, **overrides) -> dict:
    defaults = {
        "recipe_id": recipe_id,
        "pricing_agreement_id": pricing_agreement_id,
        "tank_id": tank_id,
        "batch_size_l": 100,
        "scheduled_start": "2026-09-01T08:00:00Z",
        "scheduled_end": "2026-09-01T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def batch_charge_payload(lot_id, **overrides) -> dict:
    defaults = {
        "raw_material_lot_id": lot_id,
        "charge_order": 1,
        "charged_qty_kg": 100,
    }
    defaults.update(overrides)
    return defaults


def sds_payload(ghs_classification="NON_HAZ", **overrides) -> dict:
    """SDS payload consistent with the classification by default (PRD §3.7):
    DANGER for FLAMMABLE/OXIDIZER/TOXIN, WARNING-or-NONE otherwise; empty
    hazard statements allowed only for NON_HAZ."""
    if ghs_classification in ("FLAMMABLE", "OXIDIZER", "TOXIN"):
        signal_word, statements = "DANGER", ["H225"]
    elif ghs_classification == "NON_HAZ":
        signal_word, statements = "NONE", []
    else:  # ACID / BASE
        signal_word, statements = "WARNING", ["H314"]
    defaults = {
        "ghs_classification": ghs_classification,
        "signal_word": signal_word,
        "hazard_statements": statements,
    }
    defaults.update(overrides)
    return defaults


def package_config_payload(**overrides) -> dict:
    defaults = {
        "package_type": "DRUM_205L",
        "un_rated": True,
        "package_count": 1,
    }
    defaults.update(overrides)
    return defaults


def shipment_payload(**overrides) -> dict:
    defaults = {
        "carrier_name": "ChemTrans LLC",
        "vehicle_placards": [],
        "departure_at": "2026-09-02T08:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def heel_disposal_payload(lot_id, **overrides) -> dict:
    defaults = {
        "raw_material_lot_id": lot_id,
        "heel_returned_kg": 5,
        "heel_disposed_kg": 0,
        "disposed_at": "2026-09-01T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults
