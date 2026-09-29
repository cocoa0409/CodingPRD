"""Request payload builders, one per write endpoint.

Each factory returns a valid body using the canonical values that the design
recipes rely on, and merges ``**overrides`` last so a test can perturb exactly
the one field it is probing.
"""

from __future__ import annotations

from typing import Any, Optional

from .types import (
    BoardType,
    ChangeoverFamily,
    DispositionAction,
    LotSourceType,
    OutageType,
)

JsonDict = dict[str, Any]


def _merge(base: JsonDict, overrides: JsonDict) -> JsonDict:
    """Apply overrides; an override of ``None`` keeps the key with a null value."""
    payload = dict(base)
    payload.update(overrides)
    return payload


def omitting(payload: JsonDict, *fields: str) -> JsonDict:
    """Return a copy of ``payload`` with the named keys removed entirely."""
    return {k: v for k, v in payload.items() if k not in fields}


# --------------------------------------------------------------------------- #
# Plant, line, spec, market
# --------------------------------------------------------------------------- #


def plant_payload(**overrides: Any) -> JsonDict:
    """The canonical GYP-1 plant: 60 tph calciner, 1200 t silo."""
    return _merge(
        {
            "code": "GYP-1",
            "name": "Front Range Wallboard",
            "calciner_capacity_tph": 60,
            "stucco_silo_capacity_tons": 1200,
            "energy_price_per_mmbtu": 4.2,
            "contribution_margin_per_msf": 38.5,
        },
        overrides,
    )


def board_line_payload(**overrides: Any) -> JsonDict:
    """LINE-1: 500 fpm ceiling on a 54-inch web."""
    return _merge(
        {
            "designation": "LINE-1",
            "max_speed_fpm": 500,
            "web_width_in": 54.0,
        },
        overrides,
    )


def regular_spec_payload(**overrides: Any) -> JsonDict:
    """The 1/2-inch REGULAR 4x12 SKU used as the baseline product."""
    return _merge(
        {
            "sku_code": "REG-050-4X12",
            "thickness_in": 0.5,
            "board_type": BoardType.REGULAR.value,
            "fire_rated": False,
            "board_width_in": 48.0,
            "board_length_ft": 12.0,
            "target_board_weight_lb_per_msf": 1600.0,
            "stucco_lb_per_msf": 1350.0,
            "slurry_water_stucco_ratio": 0.75,
            "line_speed_max_fpm": 480,
            "paper_tension_min_lb": 28.0,
            "paper_tension_max_lb": 46.0,
            "core_hardness_min_lbf": 15.0,
            "nail_pull_min_lbf": 77.0,
            "flexural_cross_min_lbf": 36.0,
            "max_boards_per_bundle": 48,
            "changeover_family": ChangeoverFamily.STANDARD.value,
        },
        overrides,
    )


def type_x_spec_payload(**overrides: Any) -> JsonDict:
    """The 5/8-inch TYPE_X 4x12 SKU: fire rated, FIRE_RATED changeover family."""
    return _merge(
        {
            "sku_code": "TYPEX-0625-4X12",
            "thickness_in": 0.625,
            "board_type": BoardType.TYPE_X.value,
            "fire_rated": True,
            "board_width_in": 48.0,
            "board_length_ft": 12.0,
            "target_board_weight_lb_per_msf": 2100.0,
            "stucco_lb_per_msf": 1820.0,
            "slurry_water_stucco_ratio": 0.7,
            "line_speed_max_fpm": 420,
            "paper_tension_min_lb": 32.0,
            "paper_tension_max_lb": 52.0,
            "core_hardness_min_lbf": 15.0,
            "nail_pull_min_lbf": 87.0,
            "flexural_cross_min_lbf": 40.0,
            "max_boards_per_bundle": 38,
            "changeover_family": ChangeoverFamily.FIRE_RATED.value,
        },
        overrides,
    )


def market_payload(**overrides: Any) -> JsonDict:
    """Denver Metro at 640 miles: ZONE_4, 18.5 percent fuel, 425.00 floor."""
    return _merge(
        {
            "name": "Denver Metro",
            "distance_miles": 640,
            "fuel_surcharge_pct": 18.5,
            "min_charge_usd": 425.0,
            "backhaul_credit_usd": 60.0,
        },
        overrides,
    )


# --------------------------------------------------------------------------- #
# Gypsum lots
# --------------------------------------------------------------------------- #


def synthetic_lot_payload(plant_id: str, **overrides: Any) -> JsonDict:
    """300 tonnes of Comanche FGD synthetic gypsum."""
    return _merge(
        {
            "plant_id": plant_id,
            "source_type": LotSourceType.SYNTHETIC.value,
            "supplier_name": "Comanche FGD",
            "received_tons": 300.0,
            "declared_free_moisture_pct": 9.5,
            "declared_purity_pct": 94.0,
        },
        overrides,
    )


def natural_lot_payload(plant_id: str, **overrides: Any) -> JsonDict:
    """200 tonnes of Loveland Quarry natural rock."""
    return _merge(
        {
            "plant_id": plant_id,
            "source_type": LotSourceType.NATURAL.value,
            "supplier_name": "Loveland Quarry",
            "received_tons": 200.0,
            "declared_free_moisture_pct": 2.8,
            "declared_purity_pct": 91.5,
        },
        overrides,
    )


def assay_payload(
    free_moisture_pct: float,
    purity_pct: float,
    chloride_ppm: int,
    **overrides: Any,
) -> JsonDict:
    return _merge(
        {
            "free_moisture_pct": free_moisture_pct,
            "purity_pct": purity_pct,
            "chloride_ppm": chloride_ppm,
        },
        overrides,
    )


def reject_payload(reject_note: str = "chloride too high to salvage", **overrides: Any) -> JsonDict:
    return _merge({"reject_note": reject_note}, overrides)


# --------------------------------------------------------------------------- #
# Calciner batches, feeds, stucco tests
# --------------------------------------------------------------------------- #


def calciner_batch_payload(plant_id: str, **overrides: Any) -> JsonDict:
    """The canonical B1 batch: 40 tph over a six-hour window on 2 August."""
    return _merge(
        {
            "plant_id": plant_id,
            "target_stucco_tons": 230.0,
            "calcination_temp_f": 320.0,
            "feed_rate_tph": 40.0,
            "feed_window_start": "2026-08-02T08:00:00Z",
            "feed_window_end": "2026-08-02T14:00:00Z",
        },
        overrides,
    )


def batch_feed_payload(
    lot_id: str,
    tons_fed: float,
    measured_free_moisture_pct: float,
    expected_lot_version: int,
    **overrides: Any,
) -> JsonDict:
    return _merge(
        {
            "lot_id": lot_id,
            "tons_fed": tons_fed,
            "measured_free_moisture_pct": measured_free_moisture_pct,
            "expected_lot_version": expected_lot_version,
        },
        overrides,
    )


def stucco_test_payload(
    sample_seq: int = 1,
    combined_water_pct: float = 5.6,
    free_water_pct: float = 0.18,
    set_time_minutes: float = 7.5,
    normal_consistency_cc: float = 78.0,
    **overrides: Any,
) -> JsonDict:
    """A sample inside every PASS band unless a caller moves one value."""
    return _merge(
        {
            "sample_seq": sample_seq,
            "combined_water_pct": combined_water_pct,
            "free_water_pct": free_water_pct,
            "set_time_minutes": set_time_minutes,
            "normal_consistency_cc": normal_consistency_cc,
        },
        overrides,
    )


def abort_payload(abort_reason: str = "calciner ring gear failure", **overrides: Any) -> JsonDict:
    return _merge({"abort_reason": abort_reason}, overrides)


# --------------------------------------------------------------------------- #
# Production runs
# --------------------------------------------------------------------------- #


def run_draft_payload(
    plant_id: str,
    line_id: str,
    product_spec_id: str,
    calciner_batch_id: str,
    **overrides: Any,
) -> JsonDict:
    """The canonical R1 draft: 06:00-10:00 on 3 August at 400 fpm."""
    return _merge(
        {
            "plant_id": plant_id,
            "line_id": line_id,
            "product_spec_id": product_spec_id,
            "calciner_batch_id": calciner_batch_id,
            "window_start": "2026-08-03T06:00:00Z",
            "window_end": "2026-08-03T10:00:00Z",
            "requested_planned_msf": 300.0,
            "line_speed_fpm": 400,
            "paper_tension_lb": 38.0,
            "kiln_dwell_minutes": 40,
            "kiln_exit_moisture_target_pct": 0.5,
        },
        overrides,
    )


def schedule_payload(expected_plant_version: int, **overrides: Any) -> JsonDict:
    return _merge({"expected_plant_version": expected_plant_version}, overrides)


def complete_run_payload(
    actual_msf: float = 295.0,
    scrap_msf: float = 5.0,
    edge_defect_ppm: int = 800,
    end_defect_ppm: int = 400,
    **overrides: Any,
) -> JsonDict:
    """Defect rates chosen below both auto-hold ceilings."""
    return _merge(
        {
            "actual_msf": actual_msf,
            "scrap_msf": scrap_msf,
            "edge_defect_ppm": edge_defect_ppm,
            "end_defect_ppm": end_defect_ppm,
        },
        overrides,
    )


def cancel_run_payload(
    cancel_reason: str = "customer order pulled", **overrides: Any
) -> JsonDict:
    return _merge({"cancel_reason": cancel_reason}, overrides)


def board_test_payload(
    specimen_seq: int,
    core_hardness_lbf: float = 17.0,
    nail_pull_lbf: float = 82.0,
    flexural_cross_lbf: float = 39.0,
    flexural_parallel_lbf: float = 110.0,
    exit_moisture_pct: float = 0.55,
    **overrides: Any,
) -> JsonDict:
    """A specimen above every REGULAR minimum and inside the moisture tolerance."""
    return _merge(
        {
            "specimen_seq": specimen_seq,
            "core_hardness_lbf": core_hardness_lbf,
            "nail_pull_lbf": nail_pull_lbf,
            "flexural_cross_lbf": flexural_cross_lbf,
            "flexural_parallel_lbf": flexural_parallel_lbf,
            "exit_moisture_pct": exit_moisture_pct,
        },
        overrides,
    )


#: The three passing specimens the recipes record before a quality evaluation.
PASSING_SPECIMENS: tuple[JsonDict, ...] = (
    board_test_payload(1, 17.0, 82.0, 39.0, 110.0, 0.55),
    board_test_payload(2, 16.5, 80.0, 38.0, 108.0, 0.52),
    board_test_payload(3, 18.0, 84.0, 40.0, 112.0, 0.49),
)

#: A specimen whose nail pull is below the REGULAR minimum of 77.0 lbf.
NAIL_PULL_FAILING_SPECIMEN: JsonDict = board_test_payload(4, 16.0, 70.0, 38.0, 105.0, 0.58)


def disposition_payload(
    action: str = DispositionAction.DOWNGRADE.value,
    disposition_note: str = "sold as seconds to the distributor",
    **overrides: Any,
) -> JsonDict:
    return _merge({"action": action, "disposition_note": disposition_note}, overrides)


# --------------------------------------------------------------------------- #
# Maintenance outages
# --------------------------------------------------------------------------- #


def outage_payload(
    line_id: str,
    outage_type: str = OutageType.PLANNED.value,
    window_start: str = "2026-10-05T06:00:00Z",
    window_end: str = "2026-10-07T06:00:00Z",
    scope_note: str = "kiln burner rebuild",
    **overrides: Any,
) -> JsonDict:
    """An October window, whose seasonality index of 0.90 sits on the gate."""
    return _merge(
        {
            "line_id": line_id,
            "outage_type": outage_type,
            "window_start": window_start,
            "window_end": window_end,
            "scope_note": scope_note,
        },
        overrides,
    )


def defer_payload(
    deferred_reason: str = "peak housing season backlog", **overrides: Any
) -> JsonDict:
    return _merge({"deferred_reason": deferred_reason}, overrides)


def repropose_payload(window_start: str, window_end: str, **overrides: Any) -> JsonDict:
    return _merge({"window_start": window_start, "window_end": window_end}, overrides)


def close_outage_payload(
    close_note: str = "burner and drive replaced", **overrides: Any
) -> JsonDict:
    return _merge({"close_note": close_note}, overrides)


# --------------------------------------------------------------------------- #
# Load orders
# --------------------------------------------------------------------------- #


def load_order_payload(
    run_id: str,
    market_id: str,
    bundles_count: int = 12,
    boards_per_bundle: int = 48,
    **overrides: Any,
) -> JsonDict:
    return _merge(
        {
            "run_id": run_id,
            "market_id": market_id,
            "bundles_count": bundles_count,
            "boards_per_bundle": boards_per_bundle,
        },
        overrides,
    )


def record_load_payload(loaded_bundles_count: int, **overrides: Any) -> JsonDict:
    return _merge({"loaded_bundles_count": loaded_bundles_count}, overrides)


def ship_payload(backhaul: Optional[bool] = None, **overrides: Any) -> JsonDict:
    payload: JsonDict = {}
    if backhaul is not None:
        payload["backhaul"] = backhaul
    return _merge(payload, overrides)


def cancel_load_payload(
    cancel_reason: str = "distributor rescheduled the delivery", **overrides: Any
) -> JsonDict:
    return _merge({"cancel_reason": cancel_reason}, overrides)
