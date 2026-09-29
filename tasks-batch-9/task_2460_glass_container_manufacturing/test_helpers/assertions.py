"""Per-entity shape assertions and domain invariant checkers."""

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

from prd_bench_local_runner.testing import (
    assert_timestamp_format,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    COLOR_WEAR_FACTOR,
    CULLET_STRESS_WEIGHT,
    OVER_PULL_STRESS_WEIGHT,
    PALLET_UNITS,
    POSTURE_COLD,
    POSTURE_OPERATING,
    POSTURE_REBUILD_DUE,
    POSTURE_RESTRICTED,
    REBUILD_DUE_REMAINING_PCT,
    RESTRICTED_REMAINING_PCT,
    TIMESTAMP_SUFFIX,
)


# --------------------------------------------------------------------------
# Numeric helpers
# --------------------------------------------------------------------------
def round_half_up(value, places: int) -> float:
    """Round a value half up to the given number of decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def assert_money(actual, expected, field: str = "amount") -> None:
    """A currency figure carried to 2 decimals must match exactly."""
    assert round_half_up(actual, 2) == round_half_up(expected, 2), (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_decimals(actual, expected, places: int, field: str = "value") -> None:
    """A figure carried to a fixed number of decimals must match exactly."""
    assert round_half_up(actual, places) == round_half_up(expected, places), (
        f"{field}: expected {expected} at {places}dp, got {actual}"
    )


def assert_ppm(actual, expected, field: str = "ppm") -> None:
    """Parts-per-million figures are carried to 1 decimal."""
    assert_decimals(actual, expected, 1, field)


# --------------------------------------------------------------------------
# Common audit block
# --------------------------------------------------------------------------
def assert_common_fields(entity: dict, expected_version: int = None) -> None:
    """id, created_at, updated_at and version, in the declared formats."""
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']}"
    assert_timestamp_format(entity["created_at"])
    assert_timestamp_format(entity["updated_at"])
    assert entity["created_at"].endswith(TIMESTAMP_SUFFIX) or is_iso8601_timestamp(
        entity["created_at"]
    )
    assert isinstance(entity["version"], int), "version must be an integer"
    assert entity["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"version: expected {expected_version}, got {entity['version']}"
        )


def assert_no_audit_tail(entity: dict) -> None:
    """The inspection reading carries id and created_at but no version tail."""
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']}"
    assert_timestamp_format(entity["created_at"])
    assert "version" not in entity, "an inspection reading carries no version"
    assert "updated_at" not in entity, "an inspection reading carries no updated_at"


def assert_fields_present(entity: dict, fields: Iterable[str]) -> None:
    missing = [field for field in fields if field not in entity]
    assert not missing, f"missing fields: {missing}"


# --------------------------------------------------------------------------
# Per-entity shape assertions
# --------------------------------------------------------------------------
FURNACE_FIELDS = (
    "id",
    "code",
    "design_pull_tpd",
    "refractory_life_total_units",
    "current_color",
    "refractory_consumed_units",
    "refractory_remaining_pct",
    "posture",
    "reserved_pull_tons",
    "campaign_count",
    "created_at",
    "updated_at",
    "version",
)


def assert_furnace(furnace: dict, expected_version: int = None) -> None:
    assert_fields_present(furnace, FURNACE_FIELDS)
    assert_common_fields(furnace, expected_version)
    assert furnace["posture"] in (
        POSTURE_OPERATING,
        POSTURE_RESTRICTED,
        POSTURE_REBUILD_DUE,
        POSTURE_COLD,
    )
    assert furnace["current_color"] in COLOR_WEAR_FACTOR


CAMPAIGN_FIELDS = (
    "id",
    "furnace_id",
    "code",
    "status",
    "target_pull_tpd",
    "window_start_at",
    "window_end_at",
    "rebuild_window_start_at",
    "rebuild_window_end_at",
    "projected_refractory_units_nominal",
    "melt_tons_charged",
    "packed_tons",
    "reject_loss_tons",
    "transition_loss_tons",
    "unaccounted_loss_tons",
    "created_at",
    "updated_at",
    "version",
)


def assert_campaign(campaign: dict, expected_version: int = None) -> None:
    assert_fields_present(campaign, CAMPAIGN_FIELDS)
    assert_common_fields(campaign, expected_version)


BATCH_RECIPE_FIELDS = (
    "id",
    "furnace_id",
    "code",
    "color",
    "cullet_ratio_pct",
    "soda_ash_kg_per_ton",
    "colorant_kg_per_ton",
    "cullet_stress_factor",
    "approved",
    "created_at",
    "updated_at",
    "version",
)


def assert_batch_recipe(recipe: dict, expected_version: int = None) -> None:
    assert_fields_present(recipe, BATCH_RECIPE_FIELDS)
    assert_common_fields(recipe, expected_version)
    assert isinstance(recipe["approved"], bool)


COLOR_CHANGE_FIELDS = (
    "id",
    "furnace_id",
    "status",
    "from_color",
    "to_color",
    "window_start_at",
    "window_end_at",
    "transition_loss_tons",
    "created_at",
    "updated_at",
    "version",
)


def assert_color_change(change: dict, expected_version: int = None) -> None:
    assert_fields_present(change, COLOR_CHANGE_FIELDS)
    assert_common_fields(change, expected_version)


FORMING_MACHINE_FIELDS = (
    "id",
    "furnace_id",
    "code",
    "status",
    "section_count",
    "max_cavities",
    "mounted_cavities",
    "primary_mold_family",
    "changeover_buffer_minutes",
    "created_at",
    "updated_at",
    "version",
)


def assert_forming_machine(machine: dict, expected_version: int = None) -> None:
    assert_fields_present(machine, FORMING_MACHINE_FIELDS)
    assert_common_fields(machine, expected_version)
    assert machine["mounted_cavities"] <= machine["max_cavities"], (
        "mounted cavities may never exceed the machine's cavity slots"
    )


CUSTOMER_FIELDS = (
    "id",
    "name",
    "account_code",
    "palletization_standard",
    "complaint_ppm_threshold",
    "weighted_breakage_ppm",
    "quality_standing",
    "credit_issued_usd",
    "created_at",
    "updated_at",
    "version",
)


def assert_customer(customer: dict, expected_version: int = None) -> None:
    assert_fields_present(customer, CUSTOMER_FIELDS)
    assert_common_fields(customer, expected_version)
    assert customer["palletization_standard"] in PALLET_UNITS


BOTTLE_DESIGN_FIELDS = (
    "id",
    "customer_id",
    "code",
    "status",
    "color",
    "capacity_ml",
    "nominal_weight_g",
    "min_wall_thickness_mm",
    "cavity_count",
    "target_line_speed_bpm",
    "container_price_usd",
    "mold_owner",
    "supersedes_design_id",
    "breakage_risk_index",
    "lead_time_days",
    "revision_count",
    "risk_signed_by_user_id",
    "approved_by_user_id",
    "created_at",
    "updated_at",
    "version",
)


def assert_bottle_design(design: dict, expected_version: int = None) -> None:
    assert_fields_present(design, BOTTLE_DESIGN_FIELDS)
    assert_common_fields(design, expected_version)
    assert isinstance(design["lead_time_days"], int), "lead time is a whole number of days"
    assert isinstance(design["revision_count"], int)


MOLD_SET_FIELDS = (
    "id",
    "bottle_design_id",
    "code",
    "status",
    "cavity_count",
    "mold_family",
    "owner",
    "condition_score",
    "mount_count",
    "forming_machine_id",
    "created_at",
    "updated_at",
    "version",
)


def assert_mold_set(mold_set: dict, expected_version: int = None) -> None:
    assert_fields_present(mold_set, MOLD_SET_FIELDS)
    assert_common_fields(mold_set, expected_version)


PRODUCTION_JOB_FIELDS = (
    "id",
    "campaign_id",
    "furnace_id",
    "forming_machine_id",
    "batch_recipe_id",
    "bottle_design_id",
    "mold_set_id",
    "code",
    "status",
    "window_start_at",
    "window_end_at",
    "planned_pull_tpd",
    "reserved_melt_tons",
    "produced_units",
    "changeover_minutes",
    "projected_refractory_units_nominal",
    "projected_refractory_units_stress_adjusted",
    "refractory_wear_units",
    "created_at",
    "updated_at",
    "version",
)


def assert_production_job(job: dict, expected_version: int = None) -> None:
    assert_fields_present(job, PRODUCTION_JOB_FIELDS)
    assert_common_fields(job, expected_version)


PACK_LOT_FIELDS = (
    "id",
    "production_job_id",
    "campaign_id",
    "bottle_design_id",
    "customer_id",
    "lot_code",
    "quality_status",
    "logistics_status",
    "packed_units",
    "unit_weight_g",
    "reject_units",
    "net_packed_units",
    "major_ppm",
    "minor_ppm",
    "provisional_yield_pct",
    "final_yield_pct",
    "palletization_standard",
    "pallet_count",
    "aged_until_at",
    "shipped_at",
    "created_at",
    "updated_at",
    "version",
)


def assert_pack_lot(lot: dict, expected_version: int = None) -> None:
    assert_fields_present(lot, PACK_LOT_FIELDS)
    assert_common_fields(lot, expected_version)
    assert lot["net_packed_units"] == lot["packed_units"] - lot["reject_units"], (
        "net packed units are packed units less rejects"
    )


INSPECTION_RESULT_FIELDS = (
    "id",
    "pack_lot_id",
    "defect_class",
    "defect_code",
    "rejected_units",
    "inspected_at",
    "recorded_by_user_id",
    "created_at",
)


def assert_inspection_result(reading: dict) -> None:
    assert_fields_present(reading, INSPECTION_RESULT_FIELDS)
    assert_no_audit_tail(reading)
    assert reading["rejected_units"] >= 1, "a reading counts at least one rejected unit"


COMPLAINT_FIELDS = (
    "id",
    "customer_id",
    "pack_lot_id",
    "code",
    "status",
    "reported_at",
    "affected_units",
    "filling_line_speed_bpm",
    "breakage_ppm",
    "attribution",
    "affected_pallets",
    "credit_usd",
    "investigated_by_user_id",
    "created_at",
    "updated_at",
    "version",
)


def assert_complaint(complaint: dict, expected_version: int = None) -> None:
    assert_fields_present(complaint, COMPLAINT_FIELDS)
    assert_common_fields(complaint, expected_version)


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------
def expected_posture(remaining_pct: float, has_rebuild_scheduled: bool = False) -> str:
    """The posture the cascade derives from remaining refractory life."""
    if has_rebuild_scheduled:
        return POSTURE_COLD
    if remaining_pct <= REBUILD_DUE_REMAINING_PCT:
        return POSTURE_REBUILD_DUE
    if remaining_pct <= RESTRICTED_REMAINING_PCT:
        return POSTURE_RESTRICTED
    return POSTURE_OPERATING


def assert_posture_matches_remaining(furnace: dict, has_rebuild_scheduled: bool = False) -> None:
    """The furnace's posture must agree with its remaining refractory life."""
    expected = expected_posture(furnace["refractory_remaining_pct"], has_rebuild_scheduled)
    assert furnace["posture"] == expected, (
        f"posture: expected {expected} at {furnace['refractory_remaining_pct']} percent remaining, "
        f"got {furnace['posture']}"
    )


def window_days(start_seconds: float, end_seconds: float) -> float:
    """Window length in days, keeping the fraction."""
    return (end_seconds - start_seconds) / 86400.0


def nominal_wear(pull_tpd: float, days: float, color: str) -> float:
    """The nominal refractory variant: base wear units rounded to 2 decimals."""
    return round_half_up(pull_tpd * days * COLOR_WEAR_FACTOR[color], 2)


def stress_multiplier(planned_pull_tpd: float, design_pull_tpd: float, cullet_stress: float):
    """One plus the weighted over-pull and cullet stress terms, unrounded."""
    fractional_over_pull = max(0.0, (planned_pull_tpd - design_pull_tpd) / design_pull_tpd)
    return 1.0 + OVER_PULL_STRESS_WEIGHT * fractional_over_pull + CULLET_STRESS_WEIGHT * cullet_stress


def stress_adjusted_wear(
    pull_tpd: float, days: float, color: str, design_pull_tpd: float, cullet_stress: float
) -> float:
    """The stress-adjusted refractory variant, rounded only at the end."""
    base = pull_tpd * days * COLOR_WEAR_FACTOR[color]
    return round_half_up(base * stress_multiplier(pull_tpd, design_pull_tpd, cullet_stress), 2)


def assert_melt_ledger_reconciles(campaign: dict) -> None:
    """The residual must equal charged melt less packed, transition and reject tons."""
    expected = round_half_up(
        campaign["melt_tons_charged"]
        - campaign["packed_tons"]
        - campaign["transition_loss_tons"]
        - campaign["reject_loss_tons"],
        2,
    )
    assert_money(campaign["unaccounted_loss_tons"], expected, "unaccounted_loss_tons")


def expected_pallet_count(net_packed_units: int, standard: str) -> int:
    """Pallet counts round up to the next whole pallet."""
    return math.ceil(net_packed_units / PALLET_UNITS[standard])


def assert_pallet_count(lot: dict) -> None:
    expected = expected_pallet_count(lot["net_packed_units"], lot["palletization_standard"])
    assert lot["pallet_count"] == expected, (
        f"pallet_count: expected {expected}, got {lot['pallet_count']}"
    )


def tons_from_units(units: int, unit_weight_g: float) -> float:
    """Container counts converted to tons at 2 decimals."""
    return round_half_up(units * unit_weight_g / 1000000.0, 2)


def assert_yield_ordering(lot: dict) -> None:
    """The final yield is never more optimistic than the provisional one."""
    assert lot["final_yield_pct"] <= lot["provisional_yield_pct"], (
        "final yield must not exceed the provisional yield for the same lot"
    )
