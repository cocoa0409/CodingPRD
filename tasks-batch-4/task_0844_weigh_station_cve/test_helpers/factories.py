"""Payload factories — one per entity, input fields only."""


def create_carrier_payload(**overrides) -> dict:
    defaults = {
        "usdot_number": "DOT-TEST-1",
        "legal_name": "Test Carrier",
        "irp_status": "ACTIVE",
        "ifta_status": "ACTIVE",
        "ucr_status": "ACTIVE",
    }
    defaults.update(overrides)
    return defaults


def create_driver_payload(**overrides) -> dict:
    defaults = {
        "cdl_number": "CDL-TEST-1",
        "full_name": "Test Driver",
    }
    defaults.update(overrides)
    return defaults


def create_station_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Station",
        "state_code": "CA",
    }
    # gross_weight_limit_lbs, single_axle_limit_lbs, iss_bypass_threshold are optional
    defaults.update(overrides)
    return defaults


def create_bay_payload(**overrides) -> dict:
    defaults = {
        "label": "Bay 1",
    }
    # status optional (defaults AVAILABLE)
    defaults.update(overrides)
    return defaults


def create_screening_payload(station_id, carrier_id, driver_id, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "carrier_id": carrier_id,
        "driver_id": driver_id,
        "vehicle_plate": "PLT-TEST",
        "axle_count": 5,
        "gross_weight_lbs": 86000,
        "heaviest_axle_lbs": 21000,
        "hazmat_placarded": False,
    }
    # oversize optional (defaults false)
    defaults.update(overrides)
    return defaults


def create_inspection_payload(screening_id, bay_id, **overrides) -> dict:
    defaults = {
        "screening_id": screening_id,
        "bay_id": bay_id,
        "level": "LEVEL_I",
        "scheduled_start": "2026-03-02T10:00:00Z",
        "scheduled_end": "2026-03-02T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_violation_payload(**overrides) -> dict:
    defaults = {
        "code": "393.75",
        "category": "WEIGHT",
        "severity_weight": 5,
        "oos": True,
    }
    # description optional (defaults "")
    defaults.update(overrides)
    return defaults


def create_citation_payload(inspection_id, carrier_id, **overrides) -> dict:
    defaults = {
        "inspection_id": inspection_id,
        "carrier_id": carrier_id,
        "kind": "OVERWEIGHT",
    }
    defaults.update(overrides)
    return defaults


def create_duty_log_payload(**overrides) -> dict:
    defaults = {
        "entry_type": "DRIVING",
        "start_utc": "2026-03-02T00:00:00Z",
        "end_utc": "2026-03-02T02:00:00Z",
    }
    defaults.update(overrides)
    return defaults
