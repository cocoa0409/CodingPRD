"""Payload factories — one per creatable resource, input fields only.

Every factory returns a fresh dict of PRD-declared input fields with valid
values, and accepts `**overrides` so a test can push any single field to the
value it needs. Natural keys (`site_code`, `circuit_ref`, `license_ref`,
`tier_code`) are auto-uniquified so several rows can coexist inside one test.
"""

import itertools

_counter = itertools.count(1)


def next_seq() -> int:
    """Monotonic counter used to keep natural keys unique within a test."""
    return next(_counter)


# --------------------------------------------------------------------------
# Reference geometry used by the fixtures.
#
# Tower antenna above mean sea level = 1200.0 + 45.0 = 1245.0 m.
# Premise mounting surface = 1210.0 + 4.0 = 1214.0 m.
# --------------------------------------------------------------------------

DEFAULTS = {
    "TOWER_GROUND_ELEVATION_M": 1200.0,
    "TOWER_ANTENNA_AGL_M": 45.0,
    "PREMISE_GROUND_ELEVATION_M": 1210.0,
    "PREMISE_ROOF_HEIGHT_M": 4.0,
    "PREMISE_TREE_LINE_HEIGHT_M": 3.0,
    "PREMISE_PATH_DISTANCE_KM": 5.0,
    "CIRCUIT_COMMITTED_MBPS": 500,
    "SECTOR_CAPACITY_MBPS": 25,
    "PLAN_DOWNSTREAM_MBPS": 50,
    "PLAN_MONTHLY_PRICE_CENTS": 6999,
}


def create_tower_payload(**overrides) -> dict:
    payload = {
        "site_code": f"RB-TWR-{next_seq():04d}",
        "latitude": 41.25,
        "longitude": -104.8,
        "ground_elevation_m": DEFAULTS["TOWER_GROUND_ELEVATION_M"],
        "antenna_agl_m": DEFAULTS["TOWER_ANTENNA_AGL_M"],
        "lease_landowner_name": "Hartley Ranch LLC",
        "lease_monthly_base_rent_cents": 45000,
        "lease_escalator_pct": 0.0275,
        "lease_start_date": "2023-04-01",
        "lease_term_months": 60,
    }
    payload.update(overrides)
    return payload


def create_backhaul_circuit_payload(tower_id: str, **overrides) -> dict:
    payload = {
        "tower_id": tower_id,
        "carrier_name": "Prairie Fiber",
        "circuit_ref": f"PF-CIR-{next_seq():05d}",
        "committed_mbps": DEFAULTS["CIRCUIT_COMMITTED_MBPS"],
        "monthly_cost_cents": 120000,
    }
    payload.update(overrides)
    return payload


def create_spectrum_license_payload(**overrides) -> dict:
    payload = {
        "license_ref": f"CBRS-PAL-{next_seq():05d}",
        "band": "CBRS_3_5GHZ",
        "channel_center_mhz": 3600.0,
        "channel_width_mhz": 100.0,
        "max_eirp_dbm": 47.0,
        "license_area_code": "WY-021",
        "effective_from": "2025-01-01T00:00:00Z",
        "effective_to": "2030-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_sector_payload(tower_id: str, spectrum_license_id: str, **overrides) -> dict:
    payload = {
        "tower_id": tower_id,
        "spectrum_license_id": spectrum_license_id,
        "azimuth_deg": 90.0,
        "beamwidth_deg": 65.0,
        "channel_center_mhz": 3555.0,
        "channel_width_mhz": 10.0,
        "tx_power_dbm": 25.0,
        "antenna_gain_dbi": 17.0,
        "capacity_mbps": DEFAULTS["SECTOR_CAPACITY_MBPS"],
        "max_oversubscription_ratio": 8.0,
    }
    payload.update(overrides)
    return payload


def create_service_plan_payload(**overrides) -> dict:
    payload = {
        "tier_code": f"STD{next_seq():04d}",
        "downstream_mbps": DEFAULTS["PLAN_DOWNSTREAM_MBPS"],
        "upstream_mbps": 10,
        "monthly_price_cents": DEFAULTS["PLAN_MONTHLY_PRICE_CENTS"],
        "soft_cap_gb": 600.0,
        "deprioritization_factor": 0.25,
        "sla_uptime_pct": 99.5,
        "sla_credit_method": "SLA_SHORTFALL",
        "equipment_policy": "RENTAL_OR_PURCHASE",
    }
    payload.update(overrides)
    return payload


def create_serviceability_request_payload(
    candidate_tower_id: str, requested_plan_id: str, **overrides
) -> dict:
    payload = {
        "candidate_tower_id": candidate_tower_id,
        "requested_plan_id": requested_plan_id,
        "contact_name": "Dana Reyes",
        "premise_latitude": 41.26,
        "premise_longitude": -104.76,
        "premise_ground_elevation_m": DEFAULTS["PREMISE_GROUND_ELEVATION_M"],
        "roof_height_m": DEFAULTS["PREMISE_ROOF_HEIGHT_M"],
        "declared_tree_line_height_m": DEFAULTS["PREMISE_TREE_LINE_HEIGHT_M"],
        "obstruction_class": "CLEAR",
        "path_distance_km": DEFAULTS["PREMISE_PATH_DISTANCE_KM"],
    }
    payload.update(overrides)
    return payload


def create_capacity_hold_payload(
    serviceability_request_id: str, expected_sector_version: int, **overrides
) -> dict:
    payload = {
        "serviceability_request_id": serviceability_request_id,
        "expected_sector_version": expected_sector_version,
    }
    payload.update(overrides)
    return payload


def create_subscriber_payload(
    serviceability_request_id: str, service_plan_id: str, **overrides
) -> dict:
    payload = {
        "serviceability_request_id": serviceability_request_id,
        "service_plan_id": service_plan_id,
        "billing_email": "dana.reyes@example.com",
        "equipment_mode": "RENTAL",
    }
    payload.update(overrides)
    return payload


def create_work_order_payload(subscriber_id: str, **overrides) -> dict:
    payload = {
        "subscriber_id": subscriber_id,
        "scheduled_at": "2026-08-02T15:00:00Z",
    }
    payload.update(overrides)
    return payload


def survey_payload(**overrides) -> dict:
    payload = {
        "measured_tree_line_height_m": DEFAULTS["PREMISE_TREE_LINE_HEIGHT_M"],
        "measured_roof_height_m": DEFAULTS["PREMISE_ROOF_HEIGHT_M"],
        "structure_penetration_allowed": True,
    }
    payload.update(overrides)
    return payload


def completion_payload(**overrides) -> dict:
    payload = {
        "installed_mast_height_m": 2.5,
        "radio_serial": f"CPE-SN-{next_seq():06d}",
    }
    payload.update(overrides)
    return payload


def create_coordination_payload(
    requesting_sector_id: str, neighbor_sector_id: str, **overrides
) -> dict:
    payload = {
        "requesting_sector_id": requesting_sector_id,
        "neighbor_sector_id": neighbor_sector_id,
        "proposed_channel_center_mhz": 3570.0,
        "proposed_channel_width_mhz": 20.0,
        "proposed_eirp_dbm": 42.0,
        "guard_band_mhz": 1.0,
        "effective_from": "2026-09-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def revision_payload(**overrides) -> dict:
    payload = {
        "proposed_channel_center_mhz": 3575.0,
        "proposed_channel_width_mhz": 20.0,
        "proposed_eirp_dbm": 41.0,
        "guard_band_mhz": 1.0,
    }
    payload.update(overrides)
    return payload


def create_outage_event_payload(tower_id: str, **overrides) -> dict:
    payload = {
        "tower_id": tower_id,
        "cause": "POWER",
        "started_at": "2026-08-05T02:00:00Z",
    }
    payload.update(overrides)
    return payload


def close_outage_payload(**overrides) -> dict:
    payload = {"ended_at": "2026-08-05T06:00:00Z"}
    payload.update(overrides)
    return payload


def create_outage_credit_payload(outage_event_id: str, subscriber_id: str, **overrides) -> dict:
    payload = {
        "outage_event_id": outage_event_id,
        "subscriber_id": subscriber_id,
    }
    payload.update(overrides)
    return payload


def usage_record_payload(usage_date: str, downstream_gb: float, upstream_gb: float, **overrides) -> dict:
    payload = {
        "usage_date": usage_date,
        "downstream_gb": downstream_gb,
        "upstream_gb": upstream_gb,
    }
    payload.update(overrides)
    return payload
