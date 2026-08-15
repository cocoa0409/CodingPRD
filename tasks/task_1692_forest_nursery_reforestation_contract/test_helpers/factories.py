"""Payload factories — one per creatable entity, input fields only (PRD §3, §4)."""
import uuid


def _uniq() -> str:
    return uuid.uuid4().hex[:8]


def create_landowner_payload(**overrides) -> dict:
    suffix = _uniq()
    defaults = {
        "legal_name": f"Owner {suffix}",
        "contact_email": f"owner-{suffix}@example.com",
        "tax_id": f"T-{suffix}",
    }
    defaults.update(overrides)
    return defaults


def create_seed_zone_payload(**overrides) -> dict:
    defaults = {
        "zone_code": f"Z-{_uniq()}",
        "min_elevation_ft": 1000,
        "max_elevation_ft": 2000,
    }
    defaults.update(overrides)
    return defaults


def create_seed_lot_payload(source_zone_id, **overrides) -> dict:
    defaults = {
        "source_zone_id": source_zone_id,
        "species": "DOUGLAS_FIR",
        "collected_on": "2026-07-15",
        "quantity_grams": 500,
        "germination_pct": 0.85,
    }
    defaults.update(overrides)
    return defaults


def create_crop_batch_payload(seed_lot_id, expected_seed_lot_version, **overrides) -> dict:
    defaults = {
        "seed_lot_id": seed_lot_id,
        "planned_sow_date": "2026-09-01",
        "lift_window_start": "2027-03-01",
        "lift_window_end": "2027-03-31",
        "expected_seed_lot_version": expected_seed_lot_version,
    }
    defaults.update(overrides)
    return defaults


def create_seedling_order_payload(landowner_id, destination_zone_id, **overrides) -> dict:
    defaults = {
        "landowner_id": landowner_id,
        "destination_zone_id": destination_zone_id,
        "species": "DOUGLAS_FIR",
        "quantity": 1000,
        "requested_ship_date": "2027-04-05",
    }
    defaults.update(overrides)
    return defaults


def create_allocation_payload(crop_batch_id, quantity, **overrides) -> dict:
    defaults = {
        "crop_batch_id": crop_batch_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def create_storage_unit_payload(**overrides) -> dict:
    defaults = {
        "unit_code": f"CU-{_uniq()}",
        "capacity_units": 20000,
        "temp_min_c": -2,
        "temp_max_c": 2,
    }
    defaults.update(overrides)
    return defaults


def create_storage_placement_payload(crop_batch_id, storage_unit_id, quantity, **overrides) -> dict:
    defaults = {
        "crop_batch_id": crop_batch_id,
        "storage_unit_id": storage_unit_id,
        "quantity": quantity,
        "placed_on": "2027-03-12",
    }
    defaults.update(overrides)
    return defaults


def create_planting_contract_payload(
    landowner_id, seedling_order_id, site_zone_id, **overrides
) -> dict:
    defaults = {
        "landowner_id": landowner_id,
        "seedling_order_id": seedling_order_id,
        "site_zone_id": site_zone_id,
        "acres": 10,
        "trees_per_acre": 400,
        "contingency_pct": 0,
        "planting_window_start": "2027-04-01",
        "planting_window_end": "2027-04-30",
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    defaults = {
        "crew_code": f"CR-{_uniq()}",
        "capacity_per_day": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_crew_assignment_payload(
    crew_id, planting_contract_id, start_date, end_date, planned_seedlings, **overrides
) -> dict:
    defaults = {
        "crew_id": crew_id,
        "planting_contract_id": planting_contract_id,
        "start_date": start_date,
        "end_date": end_date,
        "planned_seedlings": planned_seedlings,
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(planting_contract_id, crop_batch_id, quantity, **overrides) -> dict:
    defaults = {
        "planting_contract_id": planting_contract_id,
        "crop_batch_id": crop_batch_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def create_survival_survey_payload(planting_contract_id, surveyed_on, alive_count, **overrides) -> dict:
    defaults = {
        "planting_contract_id": planting_contract_id,
        "surveyed_on": surveyed_on,
        "alive_count": alive_count,
    }
    defaults.update(overrides)
    return defaults


def create_cost_share_enrollment_payload(landowner_id, **overrides) -> dict:
    defaults = {
        "landowner_id": landowner_id,
        "program_code": "EQIP-27",
        "enrolled_acres": 10,
        "rate_per_acre_cents": 15000,
        "cap_cents": 200000,
    }
    defaults.update(overrides)
    return defaults
