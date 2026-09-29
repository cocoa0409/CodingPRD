"""Payload factories — one per API input surface, input fields only.

Optional fields are omitted from the payload unless a value is supplied, so a
factory call can exercise a documented default (a family's
``requires_dedicated_cycle``, a qualification's ``supersedes_qualification_id``,
a release decision's ``hold_reason``) simply by leaving the argument out.  Every
factory accepts ``**overrides`` so a test can add, replace or (by passing the
sentinel) delete a single field without hand-rolling a dict.
"""

from typing import List, Optional

from .constants import TEST_DEFAULTS


# --------------------------------------------------------------------------- #
# customers
# --------------------------------------------------------------------------- #
def create_customer_payload(
    code: str = TEST_DEFAULTS["CUSTOMER_CODE"],
    name: str = TEST_DEFAULTS["CUSTOMER_NAME"],
    billing_email: str = TEST_DEFAULTS["BILLING_EMAIL"],
    **overrides,
) -> dict:
    payload = {"name": name, "code": code, "billing_email": billing_email}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# product families
# --------------------------------------------------------------------------- #
def create_product_family_payload(
    family_code: str = TEST_DEFAULTS["FAMILY_CODE"],
    cross_contamination_group: str = TEST_DEFAULTS["GROUP"],
    cleanout_minutes: int = TEST_DEFAULTS["CLEANOUT_MINUTES"],
    max_receipt_temp_c: float = TEST_DEFAULTS["MAX_RECEIPT_TEMP_C"],
    max_outbound_temp_c: float = TEST_DEFAULTS["MAX_OUTBOUND_TEMP_C"],
    requires_dedicated_cycle: Optional[bool] = None,
    **overrides,
) -> dict:
    payload = {
        "family_code": family_code,
        "cross_contamination_group": cross_contamination_group,
        "cleanout_minutes": cleanout_minutes,
        "max_receipt_temp_c": max_receipt_temp_c,
        "max_outbound_temp_c": max_outbound_temp_c,
    }
    if requires_dedicated_cycle is not None:
        payload["requires_dedicated_cycle"] = requires_dedicated_cycle
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# vessels
# --------------------------------------------------------------------------- #
def create_vessel_payload(
    vessel_code: str = TEST_DEFAULTS["VESSEL_CODE"],
    chamber_volume_liters: float = 350,
    max_pressure_mpa: float = 600.0,
    pump_ramp_rate_mpa_per_sec: float = 6.0,
    decompression_seconds: int = 12,
    basket_count: int = 4,
    hourly_operating_cost_cents: int = 90000,
    **overrides,
) -> dict:
    payload = {
        "vessel_code": vessel_code,
        "chamber_volume_liters": chamber_volume_liters,
        "max_pressure_mpa": max_pressure_mpa,
        "pump_ramp_rate_mpa_per_sec": pump_ramp_rate_mpa_per_sec,
        "decompression_seconds": decompression_seconds,
        "basket_count": basket_count,
        "hourly_operating_cost_cents": hourly_operating_cost_cents,
    }
    payload.update(overrides)
    return payload


def patch_vessel_payload(status: str, **overrides) -> dict:
    payload = {"status": status}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# cold rooms
# --------------------------------------------------------------------------- #
def create_cold_room_payload(
    room_code: str = TEST_DEFAULTS["ROOM_CODE"],
    capacity_pallets: int = 2,
    setpoint_c: float = 2.0,
    allowed_family_groups: Optional[List[str]] = None,
    **overrides,
) -> dict:
    payload = {
        "room_code": room_code,
        "capacity_pallets": capacity_pallets,
        "setpoint_c": setpoint_c,
        "allowed_family_groups": (
            allowed_family_groups
            if allowed_family_groups is not None
            else [TEST_DEFAULTS["GROUP"]]
        ),
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# product qualifications
# --------------------------------------------------------------------------- #
def create_qualification_payload(
    customer_id: str,
    product_family_id: str,
    sku_code: str = TEST_DEFAULTS["SKU_CODE"],
    version_label: str = TEST_DEFAULTS["VERSION_LABEL"],
    pressure_mpa: float = TEST_DEFAULTS["PRESSURE_MPA"],
    hold_time_seconds: int = TEST_DEFAULTS["HOLD_TIME_SECONDS"],
    max_water_temp_c: float = TEST_DEFAULTS["MAX_WATER_TEMP_C"],
    package_format: str = "POUCH",
    package_burst_pressure_mpa: float = 660.0,
    film_thickness_micron: int = 90,
    target_log_reduction: float = TEST_DEFAULTS["TARGET_LOG_REDUCTION"],
    supersedes_qualification_id: Optional[str] = None,
    **overrides,
) -> dict:
    payload = {
        "customer_id": customer_id,
        "product_family_id": product_family_id,
        "sku_code": sku_code,
        "version_label": version_label,
        "pressure_mpa": pressure_mpa,
        "hold_time_seconds": hold_time_seconds,
        "max_water_temp_c": max_water_temp_c,
        "package_format": package_format,
        "package_burst_pressure_mpa": package_burst_pressure_mpa,
        "film_thickness_micron": film_thickness_micron,
        "target_log_reduction": target_log_reduction,
    }
    if supersedes_qualification_id is not None:
        payload["supersedes_qualification_id"] = supersedes_qualification_id
    payload.update(overrides)
    return payload


def supersede_qualification_payload(
    expected_qualification_version: int,
    sku_code: str = TEST_DEFAULTS["SKU_CODE"],
    version_label: str = "REV-B",
    pressure_mpa: float = TEST_DEFAULTS["PRESSURE_MPA"],
    hold_time_seconds: int = TEST_DEFAULTS["HOLD_TIME_SECONDS"],
    max_water_temp_c: float = TEST_DEFAULTS["MAX_WATER_TEMP_C"],
    package_format: str = "POUCH",
    package_burst_pressure_mpa: float = 660.0,
    film_thickness_micron: int = 90,
    target_log_reduction: float = TEST_DEFAULTS["TARGET_LOG_REDUCTION"],
    **overrides,
) -> dict:
    """A revision carries a full replacement recipe plus the expected version."""
    payload = {
        "expected_qualification_version": expected_qualification_version,
        "sku_code": sku_code,
        "version_label": version_label,
        "pressure_mpa": pressure_mpa,
        "hold_time_seconds": hold_time_seconds,
        "max_water_temp_c": max_water_temp_c,
        "package_format": package_format,
        "package_burst_pressure_mpa": package_burst_pressure_mpa,
        "film_thickness_micron": film_thickness_micron,
        "target_log_reduction": target_log_reduction,
    }
    payload.update(overrides)
    return payload


def validation_run_payload(
    measured_pressure_mpa: float = TEST_DEFAULTS["PRESSURE_MPA"],
    measured_hold_time_seconds: int = TEST_DEFAULTS["HOLD_TIME_SECONDS"],
    achieved_log_reduction: float = 5.2,
    package_integrity_result: str = "PASS",
    units_tested: int = 50,
    leaker_count: int = 0,
    **overrides,
) -> dict:
    payload = {
        "measured_pressure_mpa": measured_pressure_mpa,
        "measured_hold_time_seconds": measured_hold_time_seconds,
        "achieved_log_reduction": achieved_log_reduction,
        "package_integrity_result": package_integrity_result,
        "units_tested": units_tested,
        "leaker_count": leaker_count,
    }
    payload.update(overrides)
    return payload


def qualification_decision_payload(
    outcome: str, decision_note: Optional[str] = None, **overrides
) -> dict:
    payload = {"outcome": outcome}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# capacity contracts
# --------------------------------------------------------------------------- #
def create_contract_payload(
    customer_id: str,
    season_code: str = TEST_DEFAULTS["SEASON_CODE"],
    window_start: str = TEST_DEFAULTS["WINDOW_START"],
    window_end: str = TEST_DEFAULTS["WINDOW_END"],
    committed_slots: int = 5,
    slot_take_or_pay_cents: int = TEST_DEFAULTS["SLOT_TAKE_OR_PAY_CENTS"],
    priority_rank: int = 1,
    peak_window_start: str = TEST_DEFAULTS["PEAK_WINDOW_START"],
    peak_window_end: str = TEST_DEFAULTS["PEAK_WINDOW_END"],
    peak_multiplier: float = TEST_DEFAULTS["PEAK_MULTIPLIER"],
    **overrides,
) -> dict:
    payload = {
        "customer_id": customer_id,
        "season_code": season_code,
        "window_start": window_start,
        "window_end": window_end,
        "committed_slots": committed_slots,
        "slot_take_or_pay_cents": slot_take_or_pay_cents,
        "priority_rank": priority_rank,
        "peak_window_start": peak_window_start,
        "peak_window_end": peak_window_end,
        "peak_multiplier": peak_multiplier,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# lots (pallets)
# --------------------------------------------------------------------------- #
def create_lot_payload(
    customer_id: str,
    qualification_id: str,
    cold_room_id: str,
    pallet_ref: str = "PAL-001",
    unit_count: int = 1000,
    gross_weight_kg: float = 640.0,
    carrier_temp_c: float = 2.5,
    ship_by: str = TEST_DEFAULTS["SHIP_BY"],
    **overrides,
) -> dict:
    payload = {
        "customer_id": customer_id,
        "qualification_id": qualification_id,
        "cold_room_id": cold_room_id,
        "pallet_ref": pallet_ref,
        "unit_count": unit_count,
        "gross_weight_kg": gross_weight_kg,
        "carrier_temp_c": carrier_temp_c,
        "ship_by": ship_by,
    }
    payload.update(overrides)
    return payload


def dock_inspection_payload(
    outcome: str = "ACCEPT", pulp_temp_c: float = 3.2, **overrides
) -> dict:
    payload = {"outcome": outcome, "pulp_temp_c": pulp_temp_c}
    payload.update(overrides)
    return payload


def release_decision_payload(
    outcome: str,
    expected_lot_version: int,
    hold_reason: Optional[str] = None,
    **overrides,
) -> dict:
    payload = {"outcome": outcome, "expected_lot_version": expected_lot_version}
    if hold_reason is not None:
        payload["hold_reason"] = hold_reason
    payload.update(overrides)
    return payload


def ship_payload(
    outbound_temp_c: float = 3.0, carrier_name: Optional[str] = "ColdLine", **overrides
) -> dict:
    payload = {"outbound_temp_c": outbound_temp_c}
    if carrier_name is not None:
        payload["carrier_name"] = carrier_name
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# vessel cycles and loads
# --------------------------------------------------------------------------- #
def create_vessel_cycle_payload(
    vessel_id: str,
    product_family_id: str,
    scheduled_start: str = TEST_DEFAULTS["CYCLE_START"],
    target_pressure_mpa: float = TEST_DEFAULTS["PRESSURE_MPA"],
    target_hold_seconds: int = TEST_DEFAULTS["HOLD_TIME_SECONDS"],
    **overrides,
) -> dict:
    payload = {
        "vessel_id": vessel_id,
        "product_family_id": product_family_id,
        "scheduled_start": scheduled_start,
        "target_pressure_mpa": target_pressure_mpa,
        "target_hold_seconds": target_hold_seconds,
    }
    payload.update(overrides)
    return payload


def create_cycle_load_payload(
    lot_id: str,
    contract_id: str,
    baskets_used: int,
    units_loaded: int,
    expected_cycle_version: int,
    **overrides,
) -> dict:
    payload = {
        "lot_id": lot_id,
        "contract_id": contract_id,
        "baskets_used": baskets_used,
        "units_loaded": units_loaded,
        "expected_cycle_version": expected_cycle_version,
    }
    payload.update(overrides)
    return payload


def cycle_log_payload(
    actual_pressure_mpa: float = TEST_DEFAULTS["PRESSURE_MPA"],
    actual_hold_seconds: int = 195,
    come_up_seconds: int = 104,
    water_temp_c: float = 7.5,
    **overrides,
) -> dict:
    payload = {
        "actual_pressure_mpa": actual_pressure_mpa,
        "actual_hold_seconds": actual_hold_seconds,
        "come_up_seconds": come_up_seconds,
        "water_temp_c": water_temp_c,
    }
    payload.update(overrides)
    return payload


def terminate_cycle_payload(
    reason: str = "intensifier seal failure mid-run", **overrides
) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


def load_inspection_payload(
    units_inspected: int = 1000, leaker_units: int = 3, **overrides
) -> dict:
    payload = {"units_inspected": units_inspected, "leaker_units": leaker_units}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# deviations and chargeback lines
# --------------------------------------------------------------------------- #
def adjudicate_deviation_payload(
    disposition: str,
    root_cause_code: str = TEST_DEFAULTS["ROOT_CAUSE_EQUIP"],
    **overrides,
) -> dict:
    payload = {"disposition": disposition, "root_cause_code": root_cause_code}
    payload.update(overrides)
    return payload


def waive_payload(
    waive_reason: str = "goodwill pending supplier claim", **overrides
) -> dict:
    payload = {"waive_reason": waive_reason}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# operations
# --------------------------------------------------------------------------- #
def clock_payload(current_utc: str, **overrides) -> dict:
    payload = {"current_utc": current_utc}
    payload.update(overrides)
    return payload
