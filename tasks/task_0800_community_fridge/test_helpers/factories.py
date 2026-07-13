"""Payload factories — one per create/mutate endpoint, input fields only (PRD §3)."""


def create_fridge_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Fridge",
        "location_label": "Test Street",
        "capacity_slots": 10,
    }
    defaults.update(overrides)
    return defaults


def create_steward_payload(**overrides) -> dict:
    defaults = {"name": "Test Steward", "email": "steward@example.org"}
    defaults.update(overrides)
    return defaults


def create_donor_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Donor",
        "donor_type": "RESTAURANT",
        "contact": "donor@example.org",
    }
    defaults.update(overrides)
    return defaults


def create_grant_payload(**overrides) -> dict:
    defaults = {"sponsor_name": "Test Sponsor", "amount_cents": 100000}
    defaults.update(overrides)
    return defaults


def create_shift_payload(steward_id, **overrides) -> dict:
    defaults = {
        "steward_id": steward_id,
        "kind": "COVERAGE",
        "start_at": "2026-03-01T09:00:00Z",
        "end_at": "2026-03-01T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def complete_shift_payload(**overrides) -> dict:
    defaults = {"miles_traveled": 0, "handled_cold_chain": False}
    defaults.update(overrides)
    return defaults


def create_offer_payload(fridge_id, **overrides) -> dict:
    defaults = {
        "fridge_id": fridge_id,
        "description": "Surplus produce",
        "estimated_quantity_kg": 3.0,
        "pickup_by": "2026-03-05T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(steward_id, expected_fridge_version, **overrides) -> dict:
    """Intake payload. allergens and surplus_offer_id are optional and omitted
    unless supplied via overrides (PRD §3.5)."""
    defaults = {
        "steward_id": steward_id,
        "food_category": "PRODUCE",
        "storage_type": "AMBIENT",
        "declared_quantity_kg": 5.0,
        "slot_footprint": 1,
        "intake_temp_c": 4.0,
        "use_by": "2026-04-01T00:00:00Z",
        "expected_fridge_version": expected_fridge_version,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(quantity_kg, **overrides) -> dict:
    defaults = {"quantity_kg": quantity_kg, "recipient_label": "anon"}
    defaults.update(overrides)
    return defaults


def create_need_payload(**overrides) -> dict:
    defaults = {
        "item_description": "Canned goods",
        "quantity_needed": 5,
        "needed_by": "2026-04-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
