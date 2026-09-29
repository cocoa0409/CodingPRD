"""Payload factories.

Every factory returns a plain dict with sensible defaults and applies
``**overrides`` last, so a test can change one field without restating the rest.
Optional inputs are omitted from the payload unless supplied, so tests that
exercise a declared default can simply leave the argument out.
"""

from typing import List, Optional


def create_jurisdiction_payload(
    code: str = "TX-HARRIS",
    name: str = "Harris County TX",
    state_code: str = "TX",
    territory_code: str = "TX-GULF",
    freight_zone: int = 3,
    exposure_category: str = "C",
    design_wind_speed_mph: float = 140,
    ground_snow_load_psf: float = 5,
    seismic_design_category: str = "A",
    max_authorized_builders: Optional[int] = 2,
    **overrides,
) -> dict:
    payload = {
        "code": code,
        "name": name,
        "state_code": state_code,
        "territory_code": territory_code,
        "freight_zone": freight_zone,
        "exposure_category": exposure_category,
        "design_wind_speed_mph": design_wind_speed_mph,
        "ground_snow_load_psf": ground_snow_load_psf,
        "seismic_design_category": seismic_design_category,
    }
    if max_authorized_builders is not None:
        payload["max_authorized_builders"] = max_authorized_builders
    payload.update(overrides)
    return payload


def loading_criteria_payload(
    exposure_category: str = "D",
    design_wind_speed_mph: float = 150,
    ground_snow_load_psf: float = 10,
    seismic_design_category: str = "B",
    **overrides,
) -> dict:
    payload = {
        "exposure_category": exposure_category,
        "design_wind_speed_mph": design_wind_speed_mph,
        "ground_snow_load_psf": ground_snow_load_psf,
        "seismic_design_category": seismic_design_category,
    }
    payload.update(overrides)
    return payload


def create_builder_payload(
    jurisdiction_id: str,
    name: str = "Gulf Steel Builders",
    tier: str = "SILVER",
    credit_limit_cents: Optional[int] = 200000000,
    **overrides,
) -> dict:
    payload = {
        "jurisdiction_id": jurisdiction_id,
        "name": name,
        "tier": tier,
    }
    if credit_limit_cents is not None:
        payload["credit_limit_cents"] = credit_limit_cents
    payload.update(overrides)
    return payload


def create_configuration_payload(
    builder_id: str,
    jurisdiction_id: str,
    clear_span_ft: float = 100,
    bay_spacing_ft: float = 25,
    bay_count: int = 4,
    eave_height_ft: float = 24,
    roof_pitch_rise_per_12: float = 1,
    panel_profile: str = "PBR",
    panel_color: str = "POLAR_WHITE",
    insulation_r_value: int = 19,
    **overrides,
) -> dict:
    payload = {
        "builder_id": builder_id,
        "jurisdiction_id": jurisdiction_id,
        "clear_span_ft": clear_span_ft,
        "bay_spacing_ft": bay_spacing_ft,
        "bay_count": bay_count,
        "eave_height_ft": eave_height_ft,
        "roof_pitch_rise_per_12": roof_pitch_rise_per_12,
        "panel_profile": panel_profile,
        "panel_color": panel_color,
        "insulation_r_value": insulation_r_value,
    }
    payload.update(overrides)
    return payload


def create_accessory_kit_payload(
    kit_type: str = "OVERHEAD_DOOR",
    quantity: int = 2,
    unit_price_cents: int = 385075,
    unit_weight_lbs: float = 640.5,
    erection_stage: str = "TRIM_ACCESSORY",
    **overrides,
) -> dict:
    payload = {
        "kit_type": kit_type,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
        "unit_weight_lbs": unit_weight_lbs,
        "erection_stage": erection_stage,
    }
    payload.update(overrides)
    return payload


def create_quote_payload(
    builder_id: str,
    configuration_id: str,
    freight_distance_miles: float = 240,
    adjustment_cents: Optional[int] = 0,
    **overrides,
) -> dict:
    payload = {
        "builder_id": builder_id,
        "configuration_id": configuration_id,
        "freight_distance_miles": freight_distance_miles,
    }
    if adjustment_cents is not None:
        payload["adjustment_cents"] = adjustment_cents
    payload.update(overrides)
    return payload


def accept_quote_payload(
    job_site_code: str = "SITE-A",
    requested_erection_start_date: str = "2026-09-15T00:00:00Z",
    site_delivery_capacity: Optional[int] = 2,
    **overrides,
) -> dict:
    payload = {
        "job_site_code": job_site_code,
        "requested_erection_start_date": requested_erection_start_date,
    }
    if site_delivery_capacity is not None:
        payload["site_delivery_capacity"] = site_delivery_capacity
    payload.update(overrides)
    return payload


def create_design_payload(
    configuration_id: str,
    expected_configuration_version: int,
    design_variant: str = "ASD",
    **overrides,
) -> dict:
    payload = {
        "configuration_id": configuration_id,
        "design_variant": design_variant,
        "expected_configuration_version": expected_configuration_version,
    }
    payload.update(overrides)
    return payload


def member_component_payload(
    mark: str = "C-1",
    component_class: str = "PRIMARY_FRAME_MEMBER",
    member_type: str = "COLUMN",
    erection_stage: str = "PRIMARY_FRAME",
    quantity: int = 10,
    length_ft: float = 24.5,
    weight_per_ft: float = 62.35,
    **overrides,
) -> dict:
    """A component of any class other than ``CONNECTION_DETAIL``."""
    payload = {
        "component_class": component_class,
        "mark": mark,
        "member_type": member_type,
        "erection_stage": erection_stage,
        "quantity": quantity,
        "length_ft": length_ft,
        "weight_per_ft": weight_per_ft,
    }
    payload.update(overrides)
    return payload


def connection_component_payload(
    mark: str = "K-1",
    connection_type: str = "KNEE",
    capacity_moment_kip_ft: float = 1100,
    erection_stage: str = "PRIMARY_FRAME",
    member_type: str = "DETAIL",
    **overrides,
) -> dict:
    """A ``CONNECTION_DETAIL`` component, which carries no weight fields."""
    payload = {
        "component_class": "CONNECTION_DETAIL",
        "mark": mark,
        "member_type": member_type,
        "erection_stage": erection_stage,
        "connection_type": connection_type,
        "capacity_moment_kip_ft": capacity_moment_kip_ft,
    }
    payload.update(overrides)
    return payload


def create_drawing_package_payload(
    design_id: str,
    jurisdiction_id: str,
    sealing_license_state: str = "TX",
    sheet_count: int = 24,
    **overrides,
) -> dict:
    payload = {
        "design_id": design_id,
        "jurisdiction_id": jurisdiction_id,
        "sealing_license_state": sealing_license_state,
        "sheet_count": sheet_count,
    }
    payload.update(overrides)
    return payload


def create_production_line_payload(
    code: str = "PL-1",
    name: str = "Plate Line 1",
    line_type: str = "PLATE_CUT_WELD",
    changeover_buffer_minutes: Optional[int] = None,
    **overrides,
) -> dict:
    payload = {"code": code, "name": name, "line_type": line_type}
    if changeover_buffer_minutes is not None:
        payload["changeover_buffer_minutes"] = changeover_buffer_minutes
    payload.update(overrides)
    return payload


def create_production_lot_payload(
    order_id: str,
    line_id: str,
    lot_type: str = "PRIMARY_FRAME_FAB",
    paint_color: str = "POLAR_WHITE",
    window_start: str = "2026-08-10T08:00:00Z",
    window_end: str = "2026-08-10T12:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "order_id": order_id,
        "line_id": line_id,
        "lot_type": lot_type,
        "paint_color": paint_color,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def create_shipment_load_payload(
    order_id: str,
    expected_order_version: int,
    component_marks: Optional[List[str]] = None,
    erection_stage: str = "PRIMARY_FRAME",
    carrier_name: str = "Gulf Freight",
    unload_window_start: str = "2026-09-16T08:00:00Z",
    unload_window_end: str = "2026-09-16T12:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "order_id": order_id,
        "carrier_name": carrier_name,
        "erection_stage": erection_stage,
        "component_marks": ["C-1"] if component_marks is None else component_marks,
        "unload_window_start": unload_window_start,
        "unload_window_end": unload_window_end,
        "expected_order_version": expected_order_version,
    }
    payload.update(overrides)
    return payload


def release_payload(expected_order_version: int, **overrides) -> dict:
    payload = {"expected_order_version": expected_order_version}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
