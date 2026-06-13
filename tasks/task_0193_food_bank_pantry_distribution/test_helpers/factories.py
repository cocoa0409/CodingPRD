"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

FAR_FUTURE_EXPIRATION = "2026-12-01T00:00:00.000Z"


def create_cold_storage_unit_payload(**overrides) -> dict:
    """ColdStorageUnit input fields: name, temp_zone, capacity_lbs (PRD §3.1)."""
    defaults = {
        "name": "Test Cooler",
        "temp_zone": "REFRIGERATED",
        "capacity_lbs": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_inventory_lot_payload(cold_storage_unit_id, **overrides) -> dict:
    """InventoryLot input fields (PRD §3.1). unit_cost_cents is optional."""
    defaults = {
        "cold_storage_unit_id": cold_storage_unit_id,
        "food_category": "PRODUCE",
        "source_type": "DONATION",
        "intake_lbs": 100,
        "expiration_date": "2026-07-01T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


def create_agency_payload(**overrides) -> dict:
    """Agency input fields (PRD §3.2). fair_share_weight, status optional."""
    defaults = {
        "name": "Test Pantry",
        "service_area": "County-Test",
    }
    defaults.update(overrides)
    return defaults


def create_allocation_cycle_payload(**overrides) -> dict:
    """AllocationCycle input fields (PRD §3.4)."""
    defaults = {
        "label": "2026-W01",
        "total_pool_lbs": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_agency_order_payload(agency_id, allocation_cycle_id, lines=None, **overrides) -> dict:
    """AgencyOrder input fields (PRD §3.5): agency_id, allocation_cycle_id, lines."""
    if lines is None:
        lines = [{"food_category": "PRODUCE", "requested_lbs": 100}]
    defaults = {
        "agency_id": agency_id,
        "allocation_cycle_id": allocation_cycle_id,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_client_household_payload(agency_id, **overrides) -> dict:
    """ClientHousehold input fields (PRD §3.2)."""
    defaults = {
        "agency_id": agency_id,
        "household_size": 1,
        "monthly_income_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_distribution_event_payload(agency_order_id, client_household_id, **overrides) -> dict:
    """DistributionEvent input fields (PRD §3.7): agency_order_id, client_household_id."""
    defaults = {
        "agency_order_id": agency_order_id,
        "client_household_id": client_household_id,
    }
    defaults.update(overrides)
    return defaults
