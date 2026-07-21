"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "SPECIES_COMMON_NAME": "Corn Snake",
    "SPECIES_SCIENTIFIC_NAME": "Pantherophis guttatus",
    "CARE_FEEDER_TYPE": "MOUSE_ADULT",
}


def create_species_payload(**overrides) -> dict:
    """Non-regulated species with a full care-sheet by default."""
    defaults = {
        "common_name": DEFAULTS["SPECIES_COMMON_NAME"],
        "scientific_name": DEFAULTS["SPECIES_SCIENTIFIC_NAME"],
        "is_regulated": False,
        "permit_class": "NONE",
        "min_quarantine_days": 0,
        "warranty_days": 30,
        "care_temp_low_c": 24,
        "care_temp_high_c": 30,
        "care_humidity_low_pct": 40,
        "care_humidity_high_pct": 60,
        "feed_interval_days": 7,
        "care_feeder_type": DEFAULTS["CARE_FEEDER_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_animal_payload(species_id, **overrides) -> dict:
    defaults = {
        "species_id": species_id,
        "morph": "Amel",
        "acquisition_cost_cents": 5000,
        "list_price_cents": 15000,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Customer",
        "email": "customer@example.com",
        "loyalty_tier": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(**overrides) -> dict:
    defaults = {
        "permit_number": "PERMIT-1",
        "permit_class": "CLASS_I",
        "issued_date": "2026-06-01T00:00:00Z",
        "expiry_date": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_sale_payload(animal_id, customer_id, **overrides) -> dict:
    defaults = {
        "animal_id": animal_id,
        "customer_id": customer_id,
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(**overrides) -> dict:
    defaults = {
        "claim_type": "DOA",
        "reason": "arrived dead",
    }
    defaults.update(overrides)
    return defaults


def create_feeder_batch_payload(**overrides) -> dict:
    defaults = {
        "feeder_type": "CRICKET",
        "size": "MEDIUM",
        "quantity_on_hand": 30,
        "unit_price_cents": 50,
        "received_date": "2026-06-15T00:00:00Z",
        "expiry_date": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "feeder_type": "CRICKET",
        "size": "MEDIUM",
        "quantity_per_shipment": 10,
        "cadence_days": 14,
    }
    defaults.update(overrides)
    return defaults


def create_habitat_build_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "spec_summary": "Custom enclosure",
        "quote_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_expo_payload(**overrides) -> dict:
    defaults = {
        "name": "Reptile Expo",
        "venue": "Convention Center",
        "start_at": "2026-08-01T00:00:00Z",
        "end_at": "2026-08-03T00:00:00Z",
        "venue_capacity": 10,
    }
    defaults.update(overrides)
    return defaults


def create_recall_payload(affected_batch_ids, **overrides) -> dict:
    defaults = {
        "reason": "contaminated lot",
        "target_feeder_type": "CRICKET",
        "affected_batch_ids": affected_batch_ids,
    }
    defaults.update(overrides)
    return defaults
