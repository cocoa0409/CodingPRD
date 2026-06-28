"""Payload factories — one per entity, input fields only.

Only fields with source: input are emitted. Required fields get sensible defaults;
optional fields (with PRD-stated defaults) are omitted unless overridden.
"""

DEFAULTS = {
    "SEASON_YEAR": 2026,
    "EARLY_BIRD_DEADLINE": "2026-03-01T00:00:00Z",
    "CREW_CAPACITY": 480,
    "HOME_BASE_ZIP": "90001",
}


def create_client_payload(**overrides) -> dict:
    """POST /clients — legal_name, account_type, contact_email, site_address."""
    defaults = {
        "legal_name": "Test Account",
        "account_type": "COMMERCIAL",
        "contact_email": "contact@test.example",
        "site_address": "1 Test Plaza",
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(**overrides) -> dict:
    """POST /clients/{id}/contracts — contract_type, season_year, early_bird_deadline,
    custom_design_surcharge_cents? (default 0)."""
    defaults = {
        "contract_type": "COMMERCIAL",
        "season_year": DEFAULTS["SEASON_YEAR"],
        "early_bird_deadline": DEFAULTS["EARLY_BIRD_DEADLINE"],
    }
    defaults.update(overrides)
    return defaults


def create_design_proposal_payload(**overrides) -> dict:
    """POST /contracts/{id}/design-proposals — theme, is_custom? (default false)."""
    defaults = {"theme": "Test Theme"}
    defaults.update(overrides)
    return defaults


def create_line_item_payload(inventory_item_id: str, **overrides) -> dict:
    """POST /design-proposals/{id}/line-items — inventory_item_id, quantity, unit_install_cents."""
    defaults = {
        "inventory_item_id": inventory_item_id,
        "quantity": 1,
        "unit_install_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_inventory_item_payload(**overrides) -> dict:
    """POST /inventory-items — sku, category, unit_replacement_cents,
    reorder_threshold? (default 0), on_hand_qty? (default 0)."""
    defaults = {
        "sku": "SKU-TEST",
        "category": "TREE",
        "unit_replacement_cents": 9000,
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    """POST /crews — crew_name, daily_capacity_minutes, home_base_zip."""
    defaults = {
        "crew_name": "Test Crew",
        "daily_capacity_minutes": DEFAULTS["CREW_CAPACITY"],
        "home_base_zip": DEFAULTS["HOME_BASE_ZIP"],
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(contract_id: str, **overrides) -> dict:
    """POST /work-orders — contract_id, job_type."""
    defaults = {
        "contract_id": contract_id,
        "job_type": "INSTALL",
    }
    defaults.update(overrides)
    return defaults


def create_visit_payload(**overrides) -> dict:
    """POST /work-orders/{id}/visits — stop_sequence, leg_distance_km, on_site_minutes."""
    defaults = {
        "stop_sequence": 1,
        "leg_distance_km": 5.0,
        "on_site_minutes": 60,
    }
    defaults.update(overrides)
    return defaults


def create_schedule_payload(crew_id: str, scheduled_date: str, **overrides) -> dict:
    """POST /work-orders/{id}/schedule — crew_id, scheduled_date."""
    defaults = {
        "crew_id": crew_id,
        "scheduled_date": scheduled_date,
    }
    defaults.update(overrides)
    return defaults


def create_storage_bay_payload(**overrides) -> dict:
    """POST /storage-bays — bay_code, capacity_units."""
    defaults = {
        "bay_code": "BAY-TEST",
        "capacity_units": 100,
    }
    defaults.update(overrides)
    return defaults


def create_storage_lot_payload(contract_id: str, storage_bay_id: str, **overrides) -> dict:
    """POST /storage-lots — contract_id, storage_bay_id, unit_count, stored_from, released_on."""
    defaults = {
        "contract_id": contract_id,
        "storage_bay_id": storage_bay_id,
        "unit_count": 10,
        "stored_from": "2027-01-01T00:00:00Z",
        "released_on": "2027-03-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_damage_report_payload(inventory_item_id: str, **overrides) -> dict:
    """POST /work-orders/{id}/damage-reports — inventory_item_id, damaged_qty."""
    defaults = {
        "inventory_item_id": inventory_item_id,
        "damaged_qty": 1,
    }
    defaults.update(overrides)
    return defaults


def create_renewal_offer_payload(expires_at: str, expected_contract_version: int, **overrides) -> dict:
    """POST /contracts/{id}/renewal-offers — expires_at, expected_contract_version."""
    defaults = {
        "expires_at": expires_at,
        "expected_contract_version": expected_contract_version,
    }
    defaults.update(overrides)
    return defaults
