"""Payload factories — one per creation endpoint, client-supplied fields only."""

from .constants import LATEX, TEST_DEFAULTS


def create_program_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["PROGRAM_NAME"],
        "fiscal_year": TEST_DEFAULTS["FISCAL_YEAR"],
        "budget_cents": TEST_DEFAULTS["BUDGET_CENTS"],
        "cost_per_participant_ceiling_cents": TEST_DEFAULTS["CEILING_CENTS"],
        "staff_hourly_rate_cents": TEST_DEFAULTS["STAFF_HOURLY_RATE_CENTS"],
        "eligible_jurisdiction_codes": list(TEST_DEFAULTS["JURISDICTIONS"]),
    }
    payload.update(overrides)
    return payload


def create_site_payload(program_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "name": TEST_DEFAULTS["SITE_NAME"],
        "address": TEST_DEFAULTS["SITE_ADDRESS"],
        "impervious_surface": True,
        "secondary_containment_liters": TEST_DEFAULTS["SECONDARY_CONTAINMENT_LITERS"],
        "storm_drain_distance_m": TEST_DEFAULTS["STORM_DRAIN_DISTANCE_M"],
        "lane_count": TEST_DEFAULTS["LANE_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_material_category_payload(program_id, spec=None, **overrides) -> dict:
    payload = {"program_id": program_id}
    payload.update(dict(spec or LATEX))
    payload.update(overrides)
    return payload


def create_resident_payload(program_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "full_name": "Ana Ruiz",
        "street_address": "12 Elm Street",
        "claimed_jurisdiction_code": "CO-ARV",
    }
    payload.update(overrides)
    return payload


def create_event_payload(program_id, site_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "site_id": site_id,
        "window_start_utc": TEST_DEFAULTS["WINDOW_START_UTC"],
        "window_end_utc": TEST_DEFAULTS["WINDOW_END_UTC"],
        "min_viable_registrations": 20,
    }
    payload.update(overrides)
    return payload


def create_staffer_payload(program_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "full_name": "Dana Reyes",
        "role_code": "UNLOAD",
        "hazwoper_expires_on": TEST_DEFAULTS["HAZWOPER_EXPIRY"],
    }
    payload.update(overrides)
    return payload


def create_lane_assignment_payload(event_id, staffer_id, **overrides) -> dict:
    payload = {
        "event_id": event_id,
        "staffer_id": staffer_id,
        "lane_number": 1,
        "start_utc": TEST_DEFAULTS["WINDOW_START_UTC"],
        "end_utc": TEST_DEFAULTS["WINDOW_END_UTC"],
    }
    payload.update(overrides)
    return payload


def create_appointment_payload(
    event_id, resident_id, expected_resident_version, category_ids, **overrides
) -> dict:
    payload = {
        "event_id": event_id,
        "resident_id": resident_id,
        "slot_start_utc": TEST_DEFAULTS["SLOT_START_UTC"],
        "waste_origin": "HOUSEHOLD",
        "declared_total_kg": 18.5,
        "declared_category_ids": list(category_ids),
        "expected_resident_version": expected_resident_version,
        "vehicle_count": 1,
    }
    payload.update(overrides)
    return payload


def create_dropoff_line_payload(
    appointment_id, material_category_id, net_weight_kg, declared_kg=None, **overrides
) -> dict:
    payload = {
        "appointment_id": appointment_id,
        "material_category_id": material_category_id,
        "declared_kg": net_weight_kg if declared_kg is None else declared_kg,
        "net_weight_kg": net_weight_kg,
    }
    payload.update(overrides)
    return payload


def create_container_payload(event_id, **overrides) -> dict:
    payload = {
        "event_id": event_id,
        "container_code": "DRUM-A1",
        "compatibility_class": "TOXIC",
        "capacity_kg": 200.0,
    }
    payload.update(overrides)
    return payload


def create_manifest_payload(
    event_id, container_ids, expected_event_version, **overrides
) -> dict:
    payload = {
        "event_id": event_id,
        "manifest_tracking_number": "MAN-0001",
        "tsdf_epa_id": TEST_DEFAULTS["TSDF_EPA_ID"],
        "container_ids": list(container_ids),
        "expected_event_version": expected_event_version,
    }
    payload.update(overrides)
    return payload
