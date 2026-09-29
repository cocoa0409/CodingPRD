"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_hall_payload(**overrides) -> dict:
    payload = {
        "name": "Test White Space",
        "code": "H-001",
        "tenant_mode": "SINGLE_TENANT",
        "design_kw_capacity": TEST_DEFAULTS["HALL_DESIGN_KW"],
        "gross_area_sqm": TEST_DEFAULTS["HALL_GROSS_AREA_SQM"],
        "cooling_redundancy": "N",
        "planned_rack_count": TEST_DEFAULTS["HALL_PLANNED_RACK_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_tenant_payload(**overrides) -> dict:
    payload = {
        "name": "Test Tenant",
        "code": "TN-001",
        "contracted_kw": TEST_DEFAULTS["TENANT_CONTRACTED_KW"],
        "contract_start_date": TEST_DEFAULTS["TENANT_CONTRACT_START"],
    }
    payload.update(overrides)
    return payload


def create_pdu_payload(hall_id: str, **overrides) -> dict:
    payload = {
        "hall_id": hall_id,
        "name": "PDU-A1",
        "feed_side": "A",
        "rated_kw": TEST_DEFAULTS["PDU_RATED_KW"],
    }
    payload.update(overrides)
    return payload


def create_busway_payload(pdu_id: str, **overrides) -> dict:
    payload = {
        "pdu_id": pdu_id,
        "name": "BW-A1",
        "rated_amps": TEST_DEFAULTS["BUSWAY_RATED_AMPS"],
        "voltage_v": TEST_DEFAULTS["BUSWAY_VOLTAGE_V"],
        "redundancy_topology": "N_PLUS_1",
    }
    payload.update(overrides)
    return payload


def create_containment_zone_payload(hall_id: str, **overrides) -> dict:
    payload = {
        "hall_id": hall_id,
        "label": "CA-1",
        "zone_type": "COLD_AISLE",
        "containment_kind": "RIGID_ROOF",
        "target_leakage_pct": TEST_DEFAULTS["ZONE_TARGET_LEAKAGE_PCT"],
        "design_static_pressure_pa": TEST_DEFAULTS["ZONE_DESIGN_STATIC_PRESSURE_PA"],
    }
    payload.update(overrides)
    return payload


def create_cooling_unit_payload(hall_id: str, **overrides) -> dict:
    payload = {
        "hall_id": hall_id,
        "name": "CU-1",
        "rated_sensible_kw": TEST_DEFAULTS["CU_RATED_SENSIBLE_KW"],
        "design_airflow_cfm": TEST_DEFAULTS["CU_DESIGN_AIRFLOW_CFM"],
        "supply_delta_t_f": TEST_DEFAULTS["CU_SUPPLY_DELTA_T_F"],
        "redundancy_role": "PRIMARY",
    }
    payload.update(overrides)
    return payload


def create_cage_payload(hall_id: str, tenant_id: str, **overrides) -> dict:
    payload = {
        "hall_id": hall_id,
        "tenant_id": tenant_id,
        "label": "CG-1",
        "perimeter_length_m": TEST_DEFAULTS["CAGE_PERIMETER_M"],
    }
    payload.update(overrides)
    return payload


def create_camera_payload(cage_id: str, **overrides) -> dict:
    payload = {
        "cage_id": cage_id,
        "device_type": "CAMERA",
        "label": "CAM-1",
        "covered_length_m": 38.0,
    }
    payload.update(overrides)
    return payload


def create_card_reader_payload(cage_id: str, **overrides) -> dict:
    payload = {
        "cage_id": cage_id,
        "device_type": "CARD_READER",
        "label": "RD-1",
        "reader_zone_label": "Z-N",
    }
    payload.update(overrides)
    return payload


def create_rack_payload(hall_id: str, containment_zone_id: str, **overrides) -> dict:
    payload = {
        "hall_id": hall_id,
        "containment_zone_id": containment_zone_id,
        "grid_row": "A",
        "grid_col": 1,
        "design_kw": TEST_DEFAULTS["RACK_DESIGN_KW"],
        "u_height": TEST_DEFAULTS["RACK_U_HEIGHT"],
        "required_feed_count": 2,
    }
    payload.update(overrides)
    return payload


def create_rack_feed_payload(rack_id: str, busway_id: str, **overrides) -> dict:
    payload = {
        "rack_id": rack_id,
        "busway_id": busway_id,
        "feed_side": "A",
        "requested_kw": TEST_DEFAULTS["FEED_REQUESTED_KW"],
        "breaker_amps": TEST_DEFAULTS["FEED_BREAKER_AMPS"],
    }
    payload.update(overrides)
    return payload


def create_commissioning_package_payload(
    hall_id: str, expected_hall_version: int, **overrides
) -> dict:
    payload = {
        "hall_id": hall_id,
        "level": "L4",
        "title": "Integrated systems test",
        "target_load_kw": 10.00,
        "expected_hall_version": expected_hall_version,
    }
    payload.update(overrides)
    return payload


def create_load_bank_test_payload(package_id: str, **overrides) -> dict:
    payload = {
        "package_id": package_id,
        "target_kw": 10.00,
        "window_start": "2026-08-05T02:00:00Z",
        "window_end": "2026-08-05T06:00:00Z",
        "step_pct_sequence": [25, 50, 75, 100],
    }
    payload.update(overrides)
    return payload


def create_mop_payload(
    hall_id: str, target_resource_type: str, target_resource_id: str, **overrides
) -> dict:
    payload = {
        "hall_id": hall_id,
        "target_resource_type": target_resource_type,
        "target_resource_id": target_resource_id,
        "title": "Planned works",
        "risk_class": "LOW",
        "backout_plan": "restore the prior configuration",
        "window_start": "2026-08-10T02:00:00Z",
        "window_end": "2026-08-10T06:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_release_packet_payload(
    hall_id: str, cage_id: str, expected_cage_version: int, **overrides
) -> dict:
    payload = {
        "hall_id": hall_id,
        "cage_id": cage_id,
        "as_built_drawing_ref": "AB-0001",
        "expected_cage_version": expected_cage_version,
    }
    payload.update(overrides)
    return payload
