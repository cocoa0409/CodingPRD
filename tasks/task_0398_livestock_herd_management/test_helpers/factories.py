"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "HERD_NAME": "Test Herd",
    "SPECIES": "CATTLE",
    "PASTURE_NAME": "Test Pen",
    "DRUG_NAME": "Test Drug",
    "RATION_NAME": "Test Ration",
    "EAR_TAG": "TAG-001",
    "BIRTH_DATE": "2024-01-01",
    "BIRTH_WEIGHT_KG": 40.0,
}


def create_herd_payload(**overrides) -> dict:
    """POST /herds — name, species, premises_id (PRD §3.1)."""
    defaults = {
        "name": DEFAULTS["HERD_NAME"],
        "species": DEFAULTS["SPECIES"],
        "premises_id": "PR-TEST-1",
    }
    defaults.update(overrides)
    return defaults


def create_pasture_payload(**overrides) -> dict:
    """POST /pastures — name, kind, capacity_au, optional rest_days (PRD §3.1)."""
    defaults = {
        "name": DEFAULTS["PASTURE_NAME"],
        "kind": "PEN",
        "capacity_au": 10.0,
    }
    defaults.update(overrides)
    return defaults


def create_drug_product_payload(**overrides) -> dict:
    """POST /drug-products — name, category, route_withdrawals, optional
    milk_withdrawal_hours (PRD §3.1)."""
    defaults = {
        "name": DEFAULTS["DRUG_NAME"],
        "category": "ANTIBIOTIC",
        "route_withdrawals": {"INJECTION_IM": 28},
    }
    defaults.update(overrides)
    return defaults


def create_feed_ration_payload(**overrides) -> dict:
    """POST /feed-rations — name, target_dmi_kg, ingredients (PRD §3.1)."""
    defaults = {
        "name": DEFAULTS["RATION_NAME"],
        "target_dmi_kg": 10.0,
        "ingredients": [
            {
                "feedstuff": "GRAIN_MIX",
                "dry_matter_pct": 0.90,
                "max_inclusion_pct": 1.00,
                "cost_per_kg_as_fed": 0.22,
            }
        ],
    }
    defaults.update(overrides)
    return defaults


def create_animal_payload(herd_id, **overrides) -> dict:
    """POST /animals — herd_id, ear_tag, sex, birth_date, birth_weight_kg;
    optional rfid, dam_animal_id, sire_animal_id (PRD §3.2)."""
    defaults = {
        "herd_id": herd_id,
        "ear_tag": DEFAULTS["EAR_TAG"],
        "sex": "STEER",
        "birth_date": DEFAULTS["BIRTH_DATE"],
        "birth_weight_kg": DEFAULTS["BIRTH_WEIGHT_KG"],
    }
    defaults.update(overrides)
    return defaults


def create_weight_payload(**overrides) -> dict:
    """POST /animals/{id}/weights — weighed_at, weight_kg, optional source (PRD §3.4)."""
    defaults = {
        "weighed_at": "2026-03-20",
        "weight_kg": 454.0,
    }
    defaults.update(overrides)
    return defaults


def create_breeding_record_payload(dam_animal_id, **overrides) -> dict:
    """POST /breeding-records — dam_animal_id, bred_on; optional sire_animal_id (PRD §3.5)."""
    defaults = {
        "dam_animal_id": dam_animal_id,
        "bred_on": "2026-02-01",
    }
    defaults.update(overrides)
    return defaults


def create_health_treatment_payload(animal_id, drug_product_id, **overrides) -> dict:
    """POST /health-treatments — animal_id, drug_product_id, route, first_dose_on,
    last_dose_on; optional dose_count (PRD §3.6)."""
    defaults = {
        "animal_id": animal_id,
        "drug_product_id": drug_product_id,
        "route": "INJECTION_IM",
        "first_dose_on": "2026-05-01",
        "last_dose_on": "2026-05-01",
    }
    defaults.update(overrides)
    return defaults


def create_movement_payload(animal_id, to_pasture_id, **overrides) -> dict:
    """POST /movement-records — animal_id, to_pasture_id, effective_from;
    optional effective_to (PRD §3.8)."""
    defaults = {
        "animal_id": animal_id,
        "to_pasture_id": to_pasture_id,
        "effective_from": "2026-03-21T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_sale_lot_payload(herd_id, **overrides) -> dict:
    """POST /sale-lots — herd_id, channel; optional pencil_shrink_pct, commission_pct (PRD §3.9)."""
    defaults = {
        "herd_id": herd_id,
        "channel": "AUCTION",
        "pencil_shrink_pct": 0,
        "commission_pct": 0.05,
    }
    defaults.update(overrides)
    return defaults


def create_ticket_payload(animal_id, gross_weight_kg, expected_sale_lot_version, **overrides) -> dict:
    """POST /sale-lots/{id}/tickets — animal_id, gross_weight_kg,
    expected_sale_lot_version (PRD §3.9, §2.6)."""
    defaults = {
        "animal_id": animal_id,
        "gross_weight_kg": gross_weight_kg,
        "expected_sale_lot_version": expected_sale_lot_version,
    }
    defaults.update(overrides)
    return defaults


def create_mortality_payload(animal_id, **overrides) -> dict:
    """POST /mortality-records — animal_id, died_on, cause; optional
    disposal_method (PRD §3.11)."""
    defaults = {
        "animal_id": animal_id,
        "died_on": "2026-03-30",
        "cause": "DISEASE",
    }
    defaults.update(overrides)
    return defaults
