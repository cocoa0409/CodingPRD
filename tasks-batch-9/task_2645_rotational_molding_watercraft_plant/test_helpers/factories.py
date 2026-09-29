"""Request-body builders for every write endpoint in PRD.md section 4.

Each factory returns a plain ``dict`` holding only the client-supplied fields
PRD.md declares for that endpoint — never a derived field, which PRD.md
section 2.8 says the service ignores. Defaults are mutually consistent so a
payload built with no overrides always satisfies the cross-field rules:

* a mould's ``nominal_charge_kg`` equals the model's ``nominal_charge_kg``
  times its ``cavity_count``, rounded to three decimals;
* a warehouse's ``footprint_capacity_cube_m3`` equals the sum of its zone
  capacities;
* the default resin lot qualifies for the default product model on grade,
  colour delta E, additive package, melt index band and regrind fraction;
* the default charge mass sits inside the model's ``charge_tolerance_pct`` of
  the mould's shot mass, and its blended regrind stays under
  ``max_regrind_pct``;
* the default cycle's ``scheduled_cooling_minutes`` is at least the model's
  ``min_cooling_minutes``, and its ``cooling_mode`` equals the default bay's
  ``airflow_mode``.

Every factory takes ``**overrides`` so a test can move exactly one field off
its valid default and leave the rest alone.
"""

import itertools
import uuid
from typing import Any

from .constants import (
    CLOCK_DEFAULT_UTC,
    REQUIRED_CERTIFICATIONS,
)

_COUNTER = itertools.count(1)


def unique_suffix() -> str:
    """Return a short suffix that is unique within one test process."""
    return f"{next(_COUNTER):03d}{uuid.uuid4().hex[:6]}"


def unique_code(prefix: str) -> str:
    """Return a globally unique code of the form ``<prefix>-<suffix>``.

    PRD.md caps every ``*_code`` field at 32 characters, so keep prefixes short.
    """
    return f"{prefix}-{unique_suffix()}"


# ----------------------------------------------------------------------
# Reference data
# ----------------------------------------------------------------------
# The default hull design: a MID kayak in linear HDPE. Every other default in
# this module is chosen to be compatible with these numbers.
DEFAULT_MODEL_NOMINAL_CHARGE_KG = 12.0
DEFAULT_MOLD_CAVITY_COUNT = 2
DEFAULT_MOLD_NOMINAL_CHARGE_KG = 24.0
DEFAULT_ZONE_CODE = "Z-A"
DEFAULT_ZONE_CAPACITY_CUBE_M3 = 20.0


def product_model_payload(**overrides: Any) -> dict[str, Any]:
    """Body for POST /product-models."""
    payload: dict[str, Any] = {
        "model_code": unique_code("PM"),
        "hull_type": "KAYAK",
        "size_class": "MID",
        "resin_grade": "HDPE_LINEAR",
        "master_color_code": "SEAFOAM",
        "max_color_delta_e": 1.5,
        "required_additive_package_code": "UV12",
        "max_regrind_pct": 30.0,
        "min_melt_index_g10min": 2.5,
        "max_melt_index_g10min": 6.0,
        "nominal_charge_kg": DEFAULT_MODEL_NOMINAL_CHARGE_KG,
        "charge_tolerance_pct": 5.0,
        "min_cooling_minutes": 30,
        "target_wall_thickness_mm": 6.0,
        "wall_thickness_min_mm": 4.5,
        "wall_cv_max_pct": 12.0,
        "impact_test_min_joules": 90.0,
        "gross_cube_m3": 2.0,
        "nest_factor": 0.5,
        "unit_weight_kg": 24.0,
        "msrp_cents": 180000,
        "warranty_basis": "PRO_RATA_AGE",
        "initial_warranty_reserve_cents": 500000,
        "seasonal_family": "PADDLE",
    }
    payload.update(overrides)
    return payload


def product_model_patch_payload(**overrides: Any) -> dict[str, Any]:
    """Body for PATCH /product-models/{product_model_id}.

    Empty by default: PRD.md makes every patchable field optional, so a test
    passes only the fields it means to change.
    """
    return dict(overrides)


def mold_payload(product_model_id: str, **overrides: Any) -> dict[str, Any]:
    """Body for POST /molds, matched to the default product model."""
    payload: dict[str, Any] = {
        "mold_code": unique_code("MLD"),
        "product_model_id": product_model_id,
        "size_class": "MID",
        "cavity_count": DEFAULT_MOLD_CAVITY_COUNT,
        "nominal_charge_kg": DEFAULT_MOLD_NOMINAL_CHARGE_KG,
        "service_interval_cycles": 10,
    }
    payload.update(overrides)
    return payload


def oven_station_payload(**overrides: Any) -> dict[str, Any]:
    """Body for POST /oven-stations; two arms and a 15 minute changeover buffer."""
    payload: dict[str, Any] = {
        "station_code": unique_code("OV"),
        "arm_count": 2,
        "max_size_class": "OVERSIZE",
        "changeover_buffer_min": 15,
        "energy_cents_per_min": 100,
    }
    payload.update(overrides)
    return payload


def cooling_bay_payload(**overrides: Any) -> dict[str, Any]:
    """Body for POST /cooling-bays; two concurrent slots, forced air."""
    payload: dict[str, Any] = {
        "bay_code": unique_code("CB"),
        "concurrent_slot_capacity": 2,
        "airflow_mode": "FORCED_AIR",
    }
    payload.update(overrides)
    return payload


def technician_payload(role_code: str, **overrides: Any) -> dict[str, Any]:
    """Body for POST /technicians.

    ``certifications`` defaults to exactly the set PRD.md requires before that
    ``role_code`` may act, so the technician is immediately usable.
    """
    payload: dict[str, Any] = {
        "employee_code": unique_code("T"),
        "full_name": f"Technician {role_code.title()}",
        "role_code": role_code,
        "certifications": list(REQUIRED_CERTIFICATIONS.get(role_code, ())),
    }
    payload.update(overrides)
    return payload


def customer_payload(**overrides: Any) -> dict[str, Any]:
    """Body for POST /customers."""
    suffix = unique_suffix()
    payload: dict[str, Any] = {
        "customer_code": f"CUST-{suffix}",
        "email": f"dealer.{suffix}@example.com",
        "region_code": "PNW",
    }
    payload.update(overrides)
    return payload


def warehouse_payload(**overrides: Any) -> dict[str, Any]:
    """Body for POST /warehouses; one zone whose capacity is the site capacity."""
    payload: dict[str, Any] = {
        "site_code": unique_code("WH"),
        "footprint_capacity_cube_m3": DEFAULT_ZONE_CAPACITY_CUBE_M3,
        "zones": [
            {
                "zone_code": DEFAULT_ZONE_CODE,
                "capacity_cube_m3": DEFAULT_ZONE_CAPACITY_CUBE_M3,
            }
        ],
        "restricted_threshold_pct": 85.0,
        "frozen_threshold_pct": 95.0,
    }
    payload.update(overrides)
    return payload


def zone(zone_code: str, capacity_cube_m3: float) -> dict[str, Any]:
    """One element of a warehouse ``zones`` array."""
    return {"zone_code": zone_code, "capacity_cube_m3": capacity_cube_m3}


def demand_forecast_bucket_payload(
    product_model_id: str, **overrides: Any
) -> dict[str, Any]:
    """Body for POST /demand-forecast-buckets, with a window around the clock default."""
    payload: dict[str, Any] = {
        "season_code": unique_code("SSN"),
        "product_model_id": product_model_id,
        "forecast_qty": 20,
        "build_ahead_cap_pct": 60.0,
        "window_start_on": "2026-07-01",
        "window_end_on": "2026-12-31",
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Resin
# ----------------------------------------------------------------------
def resin_lot_payload(**overrides: Any) -> dict[str, Any]:
    """Body for POST /resin-lots, qualified for the default product model.

    The grade, colour code, colour delta E, additive package, melt index and
    regrind fraction all sit inside the default model's declared window, and
    ``expires_on`` is well after the clock's startup default.
    """
    payload: dict[str, Any] = {
        "lot_code": unique_code("LOT"),
        "resin_grade": "HDPE_LINEAR",
        "melt_index_g10min": 4.0,
        "color_code": "SEAFOAM",
        "color_delta_e": 0.5,
        "additive_package_code": "UV12",
        "regrind_pct_by_mass": 10.0,
        "cost_cents_per_kg": 210,
        "received_kg": 500.0,
        "expires_on": "2027-12-31",
    }
    payload.update(overrides)
    return payload


def resin_charge_payload(
    molding_cycle_id: str,
    resin_lot_id: str,
    expected_resin_lot_version: int,
    **overrides: Any,
) -> dict[str, Any]:
    """Body for POST /resin-charges.

    ``charge_kg`` defaults to the default mould's full shot mass and
    ``regrind_kg`` to a tenth of it, which keeps the blended regrind fraction
    under the default model's ``max_regrind_pct``.

    ``created_by_technician_id`` is deliberately absent. PRD.md section 3.2
    treats the acting identifier as the charge's author, so tests that mean to
    exercise the identity-mismatch rule pass it explicitly as an override.
    """
    payload: dict[str, Any] = {
        "molding_cycle_id": molding_cycle_id,
        "resin_lot_id": resin_lot_id,
        "charge_kg": DEFAULT_MOLD_NOMINAL_CHARGE_KG,
        "regrind_kg": 2.4,
        "expected_resin_lot_version": expected_resin_lot_version,
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Orders and cycles
# ----------------------------------------------------------------------
def production_order_payload(
    product_model_id: str, target_warehouse_id: str, **overrides: Any
) -> dict[str, Any]:
    """Body for POST /production-orders; ``demand_bucket_id`` is left unset."""
    payload: dict[str, Any] = {
        "order_code": unique_code("POR"),
        "product_model_id": product_model_id,
        "target_warehouse_id": target_warehouse_id,
        "ordered_qty": 2,
    }
    payload.update(overrides)
    return payload


def molding_cycle_payload(
    production_order_id: str,
    oven_station_id: str,
    cooling_bay_id: str,
    expected_production_order_version: int,
    **overrides: Any,
) -> dict[str, Any]:
    """Body for POST /molding-cycles.

    The oven window opens at 09:00 on the clock's default date and runs for
    sixty minutes, then thirty minutes of forced-air cooling, which meets the
    default model's ``min_cooling_minutes``. ``mold_id`` is never sent: PRD.md
    section 3.4 has the server select the tool.

    ``operator_technician_id`` is deliberately absent. PRD.md section 3.4 takes
    the acting identifier as the cycle's operator, so tests that mean to
    exercise the identity-mismatch rule pass it explicitly as an override.
    """
    payload: dict[str, Any] = {
        "production_order_id": production_order_id,
        "oven_station_id": oven_station_id,
        "arm_index": 1,
        "cooling_bay_id": cooling_bay_id,
        "oven_start_at": "2026-08-01T09:00:00Z",
        "scheduled_oven_minutes": 60,
        "scheduled_cooling_minutes": 30,
        "oven_temp_c": 288.0,
        "arm_rpm_major": 8.0,
        "arm_rpm_minor": 2.0,
        "cooling_mode": "FORCED_AIR",
        "expected_production_order_version": expected_production_order_version,
    }
    payload.update(overrides)
    return payload


def start_oven_payload(actual_oven_start_at: str, **overrides: Any) -> dict[str, Any]:
    """Body for POST /molding-cycles/{molding_cycle_id}/start-oven."""
    payload: dict[str, Any] = {"actual_oven_start_at": actual_oven_start_at}
    payload.update(overrides)
    return payload


def enter_cooling_payload(actual_oven_end_at: str, **overrides: Any) -> dict[str, Any]:
    """Body for POST /molding-cycles/{molding_cycle_id}/enter-cooling."""
    payload: dict[str, Any] = {"actual_oven_end_at": actual_oven_end_at}
    payload.update(overrides)
    return payload


def demold_payload(actual_cooling_end_at: str, **overrides: Any) -> dict[str, Any]:
    """Body for POST /molding-cycles/{molding_cycle_id}/demold."""
    payload: dict[str, Any] = {"actual_cooling_end_at": actual_cooling_end_at}
    payload.update(overrides)
    return payload


def abort_payload(
    abort_reason: str = "OPERATOR_ABORT", **overrides: Any
) -> dict[str, Any]:
    """Body for POST /molding-cycles/{molding_cycle_id}/abort."""
    payload: dict[str, Any] = {"abort_reason": abort_reason}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Finished units
# ----------------------------------------------------------------------
def trim_payload(trim_waste_kg: float = 0.4, **overrides: Any) -> dict[str, Any]:
    """Body for POST /finished-units/{finished_unit_id}/trim."""
    payload: dict[str, Any] = {"trim_waste_kg": trim_waste_kg}
    payload.update(overrides)
    return payload


def outfit_payload(hardware_kit_serial: str | None = None, **overrides: Any) -> dict[str, Any]:
    """Body for POST /finished-units/{finished_unit_id}/outfit."""
    payload: dict[str, Any] = {
        "hardware_kit_serial": hardware_kit_serial or unique_code("HK"),
    }
    payload.update(overrides)
    return payload


# Six readings around the default model's 6.00 mm target: the mean is 6.00, the
# coefficient of variation is far under wall_cv_max_pct, and the minimum clears
# wall_thickness_min_mm, so the verdict is PASS.
PASSING_WALL_THICKNESS_POINTS: list[float] = [5.9, 6.0, 6.1, 5.95, 6.05, 6.0]


def inspect_payload(**overrides: Any) -> dict[str, Any]:
    """Body for POST /finished-units/{finished_unit_id}/inspect that passes.

    The defaults clear every gate the default product model declares, so the
    verdict is PASS and the hull becomes SELLABLE.
    """
    payload: dict[str, Any] = {
        "wall_thickness_points": list(PASSING_WALL_THICKNESS_POINTS),
        "impact_test_joules": 120.0,
        "cosmetic_defect_grade": "A",
    }
    payload.update(overrides)
    return payload


def store_payload(expected_warehouse_version: int, **overrides: Any) -> dict[str, Any]:
    """Body for POST /finished-units/{finished_unit_id}/store."""
    payload: dict[str, Any] = {
        "expected_warehouse_version": expected_warehouse_version
    }
    payload.update(overrides)
    return payload


def release_storage_payload(
    release_reason: str = "Zone rebalance", **overrides: Any
) -> dict[str, Any]:
    """Body for POST /finished-units/{finished_unit_id}/release-storage."""
    payload: dict[str, Any] = {"release_reason": release_reason}
    payload.update(overrides)
    return payload


def scrap_payload(
    scrap_reason: str = "Delamination on the hull-deck seam", **overrides: Any
) -> dict[str, Any]:
    """Body for POST /finished-units/{finished_unit_id}/scrap."""
    payload: dict[str, Any] = {"scrap_reason": scrap_reason}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Freight
# ----------------------------------------------------------------------
def shipment_payload(origin_warehouse_id: str, **overrides: Any) -> dict[str, Any]:
    """Body for POST /shipments.

    The trailer holds 5.0000 cube and 200.000 kg, which is enough for two
    default-model hulls nested and still leaves the sealed utilisation above
    the minimum PRD.md section 3.8 requires.
    """
    payload: dict[str, Any] = {
        "shipment_code": unique_code("SHP"),
        "origin_warehouse_id": origin_warehouse_id,
        "destination_zone": "Z2",
        "carrier_code": "CAR-A",
        "trailer_cube_capacity_m3": 5.0,
        "trailer_max_payload_kg": 200.0,
    }
    payload.update(overrides)
    return payload


def shipment_line_payload(
    shipment_id: str,
    finished_unit_id: str,
    expected_shipment_version: int,
    **overrides: Any,
) -> dict[str, Any]:
    """Body for POST /shipment-lines."""
    payload: dict[str, Any] = {
        "shipment_id": shipment_id,
        "finished_unit_id": finished_unit_id,
        "expected_shipment_version": expected_shipment_version,
    }
    payload.update(overrides)
    return payload


def remove_line_payload(
    remove_reason: str = "Customer changed the delivery date", **overrides: Any
) -> dict[str, Any]:
    """Body for POST /shipment-lines/{shipment_line_id}/remove."""
    payload: dict[str, Any] = {"remove_reason": remove_reason}
    payload.update(overrides)
    return payload


def depart_payload(departed_at: str, **overrides: Any) -> dict[str, Any]:
    """Body for POST /shipments/{shipment_id}/depart."""
    payload: dict[str, Any] = {"departed_at": departed_at}
    payload.update(overrides)
    return payload


def deliver_payload(delivered_at: str, **overrides: Any) -> dict[str, Any]:
    """Body for POST /shipments/{shipment_id}/deliver."""
    payload: dict[str, Any] = {"delivered_at": delivered_at}
    payload.update(overrides)
    return payload


def unseal_payload(
    unseal_reason: str = "Late line change requested by the dealer", **overrides: Any
) -> dict[str, Any]:
    """Body for POST /shipments/{shipment_id}/unseal."""
    payload: dict[str, Any] = {"unseal_reason": unseal_reason}
    payload.update(overrides)
    return payload


def cancel_shipment_payload(
    cancel_reason: str = "Carrier cancelled the trailer", **overrides: Any
) -> dict[str, Any]:
    """Body for POST /shipments/{shipment_id}/cancel."""
    payload: dict[str, Any] = {"cancel_reason": cancel_reason}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Warranty
# ----------------------------------------------------------------------
DEFAULT_STORAGE_DESCRIPTION = (
    "Kept on a padded cradle in a closed garage over the winter months."
)


def warranty_claim_payload(
    finished_unit_id: str, customer_id: str, **overrides: Any
) -> dict[str, Any]:
    """Body for POST /warranty-claims.

    The default claim is a HULL_DEFORMATION claim whose
    ``reported_deformation_mm`` clears the 3.00 mm threshold PRD.md requires
    for that claim type.
    """
    payload: dict[str, Any] = {
        "claim_code": unique_code("WC"),
        "finished_unit_id": finished_unit_id,
        "customer_id": customer_id,
        "claim_type": "HULL_DEFORMATION",
        "reported_deformation_mm": 4.5,
        "storage_description": DEFAULT_STORAGE_DESCRIPTION,
    }
    payload.update(overrides)
    return payload


def storage_review_payload(
    outcome: str = "VERIFIED",
    storage_description: str = DEFAULT_STORAGE_DESCRIPTION,
    **overrides: Any,
) -> dict[str, Any]:
    """Body for POST /warranty-claims/{warranty_claim_id}/storage-review."""
    payload: dict[str, Any] = {
        "outcome": outcome,
        "storage_description": storage_description,
    }
    payload.update(overrides)
    return payload


def waive_storage_finding_payload(
    waiver_note: str = "Dealer handling error acknowledged; goodwill waiver granted.",
    **overrides: Any,
) -> dict[str, Any]:
    """Body for POST /warranty-claims/{warranty_claim_id}/waive-storage-finding."""
    payload: dict[str, Any] = {"waiver_note": waiver_note}
    payload.update(overrides)
    return payload


def approve_claim_payload(
    expected_product_model_version: int, **overrides: Any
) -> dict[str, Any]:
    """Body for POST /warranty-claims/{warranty_claim_id}/approve."""
    payload: dict[str, Any] = {
        "expected_product_model_version": expected_product_model_version
    }
    payload.update(overrides)
    return payload


def deny_claim_payload(
    denial_reason: str = "NOT_A_MANUFACTURING_DEFECT", **overrides: Any
) -> dict[str, Any]:
    """Body for POST /warranty-claims/{warranty_claim_id}/deny."""
    payload: dict[str, Any] = {"denial_reason": denial_reason}
    payload.update(overrides)
    return payload


def return_to_queue_payload(
    return_note: str = "Hull photographs are illegible; re-open the file.",
    **overrides: Any,
) -> dict[str, Any]:
    """Body for POST /warranty-claims/{warranty_claim_id}/return-to-queue."""
    payload: dict[str, Any] = {"return_note": return_note}
    payload.update(overrides)
    return payload


def void_claim_payload(
    void_reason: str = "Adjuster re-opened the file after a second survey",
    **overrides: Any,
) -> dict[str, Any]:
    """Body for POST /warranty-claims/{warranty_claim_id}/void."""
    payload: dict[str, Any] = {"void_reason": void_reason}
    payload.update(overrides)
    return payload


def withdraw_claim_payload(
    withdraw_reason: str = "Owner changed their mind", **overrides: Any
) -> dict[str, Any]:
    """Body for POST /warranty-claims/{warranty_claim_id}/withdraw."""
    payload: dict[str, Any] = {"withdraw_reason": withdraw_reason}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Equipment, staff and account state changes
# ----------------------------------------------------------------------
def retire_mold_payload(
    retire_reason: str = "Superseded by a new tool", **overrides: Any
) -> dict[str, Any]:
    """Body for POST /molds/{mold_id}/retire."""
    payload: dict[str, Any] = {"retire_reason": retire_reason}
    payload.update(overrides)
    return payload


def service_hold_payload(hold_note: str | None = None, **overrides: Any) -> dict[str, Any]:
    """Body for POST /molds/{mold_id}/service-hold; the note is optional."""
    payload: dict[str, Any] = {}
    if hold_note is not None:
        payload["hold_note"] = hold_note
    payload.update(overrides)
    return payload


def complete_service_payload(
    service_note: str | None = None, **overrides: Any
) -> dict[str, Any]:
    """Body for POST /molds/{mold_id}/complete-service; the note is optional."""
    payload: dict[str, Any] = {}
    if service_note is not None:
        payload["service_note"] = service_note
    payload.update(overrides)
    return payload


def mark_down_payload(down_reason: str = "Burner service", **overrides: Any) -> dict[str, Any]:
    """Body for the oven station and cooling bay mark-down endpoints."""
    payload: dict[str, Any] = {"down_reason": down_reason}
    payload.update(overrides)
    return payload


def suspend_payload(suspend_reason: str = "Credit hold", **overrides: Any) -> dict[str, Any]:
    """Body for the technician and customer suspend endpoints."""
    payload: dict[str, Any] = {"suspend_reason": suspend_reason}
    payload.update(overrides)
    return payload


def acknowledge_storage_guidance_payload(
    acknowledged_at: str = CLOCK_DEFAULT_UTC, **overrides: Any
) -> dict[str, Any]:
    """Body for POST /customers/{customer_id}/acknowledge-storage-guidance."""
    payload: dict[str, Any] = {"acknowledged_at": acknowledged_at}
    payload.update(overrides)
    return payload


def quarantine_payload(
    quarantine_reason: str = "Colour drift audit", **overrides: Any
) -> dict[str, Any]:
    """Body for POST /resin-lots/{resin_lot_id}/quarantine."""
    payload: dict[str, Any] = {"quarantine_reason": quarantine_reason}
    payload.update(overrides)
    return payload


def release_quarantine_payload(
    release_note: str = "Colour audit closed; lot returned to service",
    **overrides: Any,
) -> dict[str, Any]:
    """Body for POST /resin-lots/{resin_lot_id}/release-quarantine."""
    payload: dict[str, Any] = {"release_note": release_note}
    payload.update(overrides)
    return payload


def release_charge_payload(
    release_reason: str | None = None, **overrides: Any
) -> dict[str, Any]:
    """Body for POST /resin-charges/{resin_charge_id}/release; the reason is optional."""
    payload: dict[str, Any] = {}
    if release_reason is not None:
        payload["release_reason"] = release_reason
    payload.update(overrides)
    return payload


def cancel_order_payload(
    cancel_reason: str = "Customer withdrew the order", **overrides: Any
) -> dict[str, Any]:
    """Body for POST /production-orders/{production_order_id}/cancel."""
    payload: dict[str, Any] = {"cancel_reason": cancel_reason}
    payload.update(overrides)
    return payload


def clock_payload(current_utc: str = CLOCK_DEFAULT_UTC, **overrides: Any) -> dict[str, Any]:
    """Body for POST /_clock/set_current_utc."""
    payload: dict[str, Any] = {"current_utc": current_utc}
    payload.update(overrides)
    return payload
