"""Payload factories: valid-by-default request bodies with keyword overrides.

Every default here satisfies the declared type ranges, so a factory call with
no overrides always produces an acceptable payload. Tests override exactly the
fields the behaviour under test depends on.
"""

from typing import Optional

from .constants import CLOCK_EPOCH
from .types import (
    DefectClass,
    GlassColor,
    MoldFamily,
    MoldOwner,
    PalletizationStandard,
)

# Window anchors expressed against the logical clock's starting instant.
DAY0 = "2026-08-01T00:00:00Z"
DAY1 = "2026-08-02T00:00:00Z"
DAY2 = "2026-08-03T00:00:00Z"
DAY3 = "2026-08-04T00:00:00Z"
DAY4 = "2026-08-05T00:00:00Z"
DAY5 = "2026-08-06T00:00:00Z"
DAY10 = "2026-08-11T00:00:00Z"
DAY30 = "2026-08-31T00:00:00Z"


def _merge(defaults: dict, overrides: dict) -> dict:
    payload = dict(defaults)
    payload.update(overrides)
    return payload


def furnace_payload(**overrides) -> dict:
    """A furnace with a refractory budget large enough to stay OPERATING."""
    return _merge(
        {
            "code": "FUR-1",
            "design_pull_tpd": 300.00,
            "refractory_life_total_units": 100000.00,
        },
        overrides,
    )


def customer_payload(**overrides) -> dict:
    return _merge(
        {
            "name": "Northline Bottling",
            "account_code": "ACC-1",
            "palletization_standard": PalletizationStandard.EURO,
            "complaint_ppm_threshold": 5000.00,
        },
        overrides,
    )


def campaign_payload(furnace_id: str, **overrides) -> dict:
    """A two-day campaign at design pull, so the pull pool is 600.00 tons."""
    return _merge(
        {
            "furnace_id": furnace_id,
            "code": "CMP-1",
            "target_pull_tpd": 300.00,
            "window_start_at": DAY0,
            "window_end_at": DAY2,
        },
        overrides,
    )


def batch_recipe_payload(furnace_id: str, **overrides) -> dict:
    """A FLINT recipe below the 45.00 cullet floor, so cullet stress is 0.0000."""
    return _merge(
        {
            "furnace_id": furnace_id,
            "code": "BR-1",
            "color": GlassColor.FLINT,
            "cullet_ratio_pct": 40.00,
            "soda_ash_kg_per_ton": 190.00,
            "colorant_kg_per_ton": 0.00,
        },
        overrides,
    )


def forming_machine_payload(furnace_id: str, **overrides) -> dict:
    return _merge(
        {
            "furnace_id": furnace_id,
            "code": "FM-1",
            "section_count": 10,
            "max_cavities": 40,
            "primary_mold_family": MoldFamily.NNPB,
            "changeover_buffer_minutes": 45,
        },
        overrides,
    )


def color_change_payload(furnace_id: str, **overrides) -> dict:
    return _merge(
        {
            "furnace_id": furnace_id,
            "to_color": GlassColor.AMBER,
            "window_start_at": DAY0,
            "window_end_at": DAY1,
            "transition_loss_tons": 30.00,
        },
        overrides,
    )


def bottle_design_payload(customer_id: str, **overrides) -> dict:
    """A design whose risk index is 9.60 and lead time 55 days at submission."""
    return _merge(
        {
            "customer_id": customer_id,
            "code": "BD-1",
            "color": GlassColor.FLINT,
            "capacity_ml": 500.00,
            "nominal_weight_g": 180.00,
            "min_wall_thickness_mm": 1.80,
            "cavity_count": 8,
            "target_line_speed_bpm": 200.00,
            "container_price_usd": 0.2500,
            "mold_owner": MoldOwner.PLANT,
        },
        overrides,
    )


def mold_set_payload(bottle_design_id: str, **overrides) -> dict:
    """Tooling that matches the default design cavity count and machine family."""
    return _merge(
        {
            "bottle_design_id": bottle_design_id,
            "code": "MS-1",
            "cavity_count": 8,
            "mold_family": MoldFamily.NNPB,
            "owner": MoldOwner.PLANT,
            "condition_score": 90,
        },
        overrides,
    )


def production_job_payload(
    campaign_id: str,
    furnace_id: str,
    forming_machine_id: str,
    batch_recipe_id: str,
    bottle_design_id: str,
    expected_furnace_version: int,
    mold_set_id: Optional[str] = None,
    **overrides,
) -> dict:
    """A one-day job at design pull, reserving 300.00 tons of the pull pool."""
    payload = {
        "campaign_id": campaign_id,
        "furnace_id": furnace_id,
        "forming_machine_id": forming_machine_id,
        "batch_recipe_id": batch_recipe_id,
        "bottle_design_id": bottle_design_id,
        "code": "PJ-1",
        "window_start_at": DAY0,
        "window_end_at": DAY1,
        "planned_pull_tpd": 300.00,
        "expected_furnace_version": expected_furnace_version,
    }
    if mold_set_id is not None:
        payload["mold_set_id"] = mold_set_id
    return _merge(payload, overrides)


def close_job_payload(outcome: str = "COMPLETED", **overrides) -> dict:
    payload = {"outcome": outcome}
    if outcome == "COMPLETED":
        payload["produced_units"] = 3000000
    return _merge(payload, overrides)


def inspection_result_payload(**overrides) -> dict:
    return _merge(
        {
            "defect_class": DefectClass.MINOR,
            "defect_code": "BLISTER",
            "rejected_units": 1,
            "inspected_at": DAY1,
        },
        overrides,
    )


def complaint_payload(customer_id: str, pack_lot_id: str, **overrides) -> dict:
    return _merge(
        {
            "customer_id": customer_id,
            "pack_lot_id": pack_lot_id,
            "code": "CMP-COMPLAINT-1",
            "reported_at": DAY4,
            "affected_units": 1000,
            "filling_line_speed_bpm": 200.00,
        },
        overrides,
    )


def investigate_payload(attribution: str = "PLANT", **overrides) -> dict:
    return _merge({"attribution": attribution}, overrides)


def settle_payload(settlement: str = "CREDIT", **overrides) -> dict:
    return _merge({"settlement": settlement}, overrides)


def lightweighting_program_payload(
    baseline_design_id: str, expected_design_version: int, **overrides
) -> dict:
    return _merge(
        {
            "baseline_design_id": baseline_design_id,
            "code": "LWP-1",
            "target_weight_g": 170.00,
            "annual_volume_units": 1000000,
            "resin_free_glass_price_per_kg": 0.5000,
            "expected_design_version": expected_design_version,
        },
        overrides,
    )


def customer_decision_payload(decision: str = "PILOT", **overrides) -> dict:
    return _merge({"decision": decision}, overrides)


def rebuild_window_payload(**overrides) -> dict:
    return _merge(
        {"rebuild_window_start_at": DAY3, "rebuild_window_end_at": DAY5},
        overrides,
    )


def return_from_repair_payload(condition_score: int = 90, **overrides) -> dict:
    return _merge({"condition_score": condition_score}, overrides)


def palletization_standard_payload(standard: str, **overrides) -> dict:
    return _merge({"palletization_standard": standard}, overrides)


def clock_payload(current_utc: str = CLOCK_EPOCH, **overrides) -> dict:
    return _merge({"current_utc": current_utc}, overrides)
