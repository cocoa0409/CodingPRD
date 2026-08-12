"""Payload factories — one per entity, input fields only.

Clock discipline: the logical clock starts at 2026-05-01T00:00:00Z. Default
windows below place the mix inside the morning of 2026-05-01; fixtures set the
clock to 2026-05-01T08:00:00Z before mixing so the window is live.
"""

FORMULATION_DEFAULTS = {
    "code": "EPX-DEFAULT",
    "name": "Default Epoxy",
    "chemistry_family": "EPOXY",
    "moisture_sensitive": False,
    "solvent_content_pct": 5.0,
    "flash_point_c": 80.0,
    "pot_life_minutes": 240,
    "shelf_life_months": 6,
    "spec_min_bond_strength_mpa": 12.0,
    "min_remaining_shelf_life_days": 90,
}


def create_formulation_payload(**overrides) -> dict:
    defaults = dict(FORMULATION_DEFAULTS)
    defaults.update(overrides)
    return defaults


VESSEL_DEFAULTS = {"vessel_code": "V-DEFAULT", "capacity_liters": 500}


def create_vessel_payload(**overrides) -> dict:
    defaults = dict(VESSEL_DEFAULTS)
    defaults.update(overrides)
    return defaults


DRY_ROOM_DEFAULTS = {"room_code": "DR-DEFAULT", "max_concurrent_runs": 2, "humidity_limit_pct": 10.0}


def create_dry_room_payload(**overrides) -> dict:
    defaults = dict(DRY_ROOM_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_batch_payload(formulation_id, vessel_id, **overrides) -> dict:
    defaults = {
        "formulation_id": formulation_id,
        "vessel_id": vessel_id,
        "mix_start_at": "2026-05-01T08:00:00Z",
        "mix_end_at": "2026-05-01T09:00:00Z",
        "batch_volume_ml": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_run_payload(batch_id, **overrides) -> dict:
    defaults = {
        "batch_id": batch_id,
        "pack_format": "CARTRIDGE",
        "unit_volume_ml": 310,
        "planned_units": 3,
        "planned_start_at": "2026-05-01T08:10:00Z",
        "planned_end_at": "2026-05-01T09:30:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_exposure_event_payload(**overrides) -> dict:
    defaults = {"exposure_minutes": 10, "occurred_at": "2026-05-01T08:20:00Z"}
    defaults.update(overrides)
    return defaults


PASSING_FULL_SPECIMENS = [13.0, 12.5, 12.4, 12.3, 12.6]


def create_cure_test_payload(**overrides) -> dict:
    defaults = {"method": "FULL", "specimens": list(PASSING_FULL_SPECIMENS)}
    defaults.update(overrides)
    return defaults


def create_distributor_payload(**overrides) -> dict:
    defaults = {
        "name": "Dist Default",
        "credit_limit_cents": 1000000,
        "contact_email": "d@x.com",
    }
    defaults.update(overrides)
    return defaults


def create_formulation_request_payload(distributor_id, **overrides) -> dict:
    defaults = {
        "distributor_id": distributor_id,
        "contact_name": "Lee",
        "target_substrate": "aluminum",
        "required_bond_strength_mpa": 15.0,
        "application_notes": "high peel strength",
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(distributor_id, formulation_id, **overrides) -> dict:
    defaults = {
        "distributor_id": distributor_id,
        "formulation_id": formulation_id,
        "unit_price_cents": 2000,
        "max_consigned_value_cents": 900000,
        "reorder_threshold_units": 0,
        "reorder_qty_units": 100,
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(distributor_id, **overrides) -> dict:
    defaults = {
        "shipment_kind": "SALE",
        "distributor_id": distributor_id,
        "transport_mode": "ROAD",
        "ship_date": "2026-06-01",
    }
    defaults.update(overrides)
    return defaults


def create_consumption_report_payload(expected_agreement_version, **overrides) -> dict:
    defaults = {
        "period": "2026-06",
        "consumed_units": 5,
        "expected_agreement_version": expected_agreement_version,
    }
    defaults.update(overrides)
    return defaults


def create_convert_payload(**overrides) -> dict:
    defaults = {
        "formulation_code": "TS-9001",
        "formulation_name": "TS 9001",
        "chemistry_family": "EPOXY",
        "moisture_sensitive": False,
        "solvent_content_pct": 10.0,
        "flash_point_c": 70.0,
        "pot_life_minutes": 180,
        "shelf_life_months": 12,
        "spec_min_bond_strength_mpa": 15.0,
        "min_remaining_shelf_life_days": 60,
    }
    defaults.update(overrides)
    return defaults
