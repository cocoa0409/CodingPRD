"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULT_PIECE = {"piece_tag": "P-1", "length_ft": 8.0, "width_in": 5.5, "thickness_in": 1.5}


def create_plant_payload(**overrides) -> dict:
    defaults = {"plant_name": "Cascade Treating", "alsc_license_number": "ALSC-CA-0042"}
    defaults.update(overrides)
    return defaults


def create_cylinder_payload(**overrides) -> dict:
    defaults = {
        "cylinder_code": "CYL-1",
        "max_volume_mbf": 50.0,
        "supported_process_types": ["FULL_CELL"],
    }
    defaults.update(overrides)
    return defaults


def create_preservative_payload(**overrides) -> dict:
    defaults = {
        "chemical_family": "CCA",
        "concentrate_assay_pct": 6.0,
        "inventory_gallons": 5000.0,
        "min_working_assay_pct": 5.0,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {"customer_name": "Acme Fence Supply", "credit_limit_cents": 100000000}
    defaults.update(overrides)
    return defaults


def create_charge_payload(**overrides) -> dict:
    defaults = {
        "ownership_type": "PLANT_STOCK",
        "species_group": "SYP",
        "use_category": "UC3B",
        "volume_mbf": 5.0,
        "piece_manifest": [dict(DEFAULT_PIECE)],
    }
    defaults.update(overrides)
    return defaults


def create_cycle_payload(preservative_id, **overrides) -> dict:
    defaults = {
        "process_type": "FULL_CELL",
        "preservative_id": preservative_id,
        "vacuum_inhg": 25.0,
        "pressure_psi": 140.0,
        "pressure_minutes": 60,
    }
    defaults.update(overrides)
    return defaults


def create_assay_payload(cycle_id, mean_retention_pcf, min_sample_retention_pcf, **overrides) -> dict:
    defaults = {
        "cycle_id": cycle_id,
        "assay_method": "TITRATION",
        "sample_count": 5,
        "mean_retention_pcf": mean_retention_pcf,
        "min_sample_retention_pcf": min_sample_retention_pcf,
        "recorded_by_agency": "PLANT_LAB",
        "recorded_at": "2026-08-10T18:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(**overrides) -> dict:
    defaults = {
        "agency_code": "ALSC",
        "inspection_window_start": "2026-08-01T00:00:00Z",
        "inspection_window_end": "2027-01-01T00:00:00Z",
        "charges_in_scope": [],
        "severity": "MINOR",
    }
    defaults.update(overrides)
    return defaults


def create_drip_log_payload(**overrides) -> dict:
    defaults = {
        "pad_code": "PAD-A",
        "entered_pad_at": "2026-08-10T18:00:00Z",
        "exited_pad_at": "2026-08-12T18:30:00Z",
        "drip_volume_liters": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_slot_payload(**overrides) -> dict:
    defaults = {
        "slot_start": "2026-08-10T07:00:00Z",
        "slot_end": "2026-08-12T23:59:00Z",
        "slot_kind": "TREATMENT",
    }
    defaults.update(overrides)
    return defaults


def create_warranty_payload(expected_charge_version, **overrides) -> dict:
    defaults = {
        "registered_by_user_id": "op-1",
        "warranty_term_years": 25,
        "expected_charge_version": expected_charge_version,
    }
    defaults.update(overrides)
    return defaults
