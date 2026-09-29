"""Entity assertions and domain invariant checkers."""

import pytest

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)


def assert_common_fields(data: dict) -> None:
    """Every resource carries a UUID id and an ISO 8601 created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"


def assert_mutable_common_fields(data: dict) -> None:
    """Most resources also carry updated_at and an integer version starting at 1."""
    assert_common_fields(data)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_immutable_common_fields(data: dict) -> None:
    """Cultivars and scouting observations carry no updated_at and no version at all."""
    assert_common_fields(data)
    assert "updated_at" not in data, "an immutable row must not carry updated_at"
    assert "version" not in data, "an immutable row must not carry version"


# --------------------------------------------------------------------------
# Zone
# --------------------------------------------------------------------------


def assert_zone(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert isinstance(data["code"], str) and 1 <= len(data["code"]) <= 16
    assert data["glazing_type"] in ("GLASS", "POLY")
    assert 1000 <= data["area_sqft"] <= 200000
    assert isinstance(data["has_thermal_screen"], bool)
    assert isinstance(data["has_supplemental_lighting"], bool)
    assert isinstance(data["chp_connected"], bool)
    assert 0 <= data["hive_slot_capacity"] <= 40
    assert data["status"] in ("IDLE", "PLANTED", "HARVESTING", "TURNAROUND")
    assert data["ipm_posture"] in ("NORMAL", "SCOUT_ALERT", "LOCKED")
    assert data["irrigation_posture"] in ("NORMAL", "WATCH", "LOCKED")
    assert data["open_pest_alert_count"] >= 0
    assert data["drain_alarm_count"] >= 0
    assert data["hive_slots_used"] >= 0
    assert data["climate_plan_revision"] >= 0
    assert_zone_budget_conserved(data)
    assert_zone_hive_slots_within_capacity(data)


def assert_zone_budget_conserved(zone: dict) -> None:
    """labor_budget_committed_usd plus labor_budget_remaining_usd equals labor_budget_usd."""
    committed = zone["labor_budget_committed_usd"]
    remaining = zone["labor_budget_remaining_usd"]
    total = zone["labor_budget_usd"]
    assert_cost_precision(committed)
    assert_cost_precision(remaining)
    assert committed + remaining == pytest.approx(total, abs=0.01), (
        f"labor budget must be conserved: {committed} + {remaining} != {total}"
    )


def assert_zone_hive_slots_within_capacity(zone: dict) -> None:
    assert zone["hive_slots_used"] <= zone["hive_slot_capacity"], (
        f"hive_slots_used {zone['hive_slots_used']} exceeds capacity "
        f"{zone['hive_slot_capacity']}"
    )


def assert_zone_postures(
    zone: dict,
    ipm_posture: str = None,
    irrigation_posture: str = None,
    status: str = None,
) -> None:
    if ipm_posture is not None:
        assert zone["ipm_posture"] == ipm_posture, (
            f"expected ipm_posture {ipm_posture}, got {zone['ipm_posture']}"
        )
    if irrigation_posture is not None:
        assert zone["irrigation_posture"] == irrigation_posture, (
            f"expected irrigation_posture {irrigation_posture}, "
            f"got {zone['irrigation_posture']}"
        )
    if status is not None:
        assert zone["status"] == status, (
            f"expected status {status}, got {zone['status']}"
        )


# --------------------------------------------------------------------------
# Variety
# --------------------------------------------------------------------------


def assert_variety(data: dict) -> None:
    assert_immutable_common_fields(data)
    assert data["crop_type"] in ("TOMATO", "CUCUMBER", "PEPPER")
    assert 4 <= data["cycle_length_weeks"] <= 60
    assert 2 <= data["first_harvest_week"] <= data["cycle_length_weeks"]
    assert 0 < data["plant_density_per_sqft"] <= 2
    assert isinstance(data["yield_curve_lbs_per_sqft"], list)
    assert len(data["yield_curve_lbs_per_sqft"]) == (
        data["cycle_length_weeks"] - data["first_harvest_week"] + 1
    ), "yield curve length must equal cycle_length_weeks - first_harvest_week + 1"
    assert all(value >= 0 for value in data["yield_curve_lbs_per_sqft"])
    assert 0 <= data["grade_a_ratio_pct"] <= 100
    assert isinstance(data["requires_pollination"], bool)
    assert 0 < data["ec_target_ms"] <= 6


# --------------------------------------------------------------------------
# Crop cycle
# --------------------------------------------------------------------------


def assert_crop_cycle(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert data["status"] in (
        "PLANNED",
        "TRANSPLANTED",
        "PRODUCTION",
        "TERMINATION_SCHEDULED",
        "TERMINATED",
        "ABORTED",
    )
    assert data["plants_transplanted"] >= 1
    assert isinstance(data["expected_weekly_yield_lbs"], list)
    assert data["density_factor"] <= 1.2, "density_factor is capped at 1.2"
    assert data["baseline_total_yield_lbs"] >= 0
    assert data["expected_total_yield_lbs"] >= 0
    assert data["cumulative_harvested_lbs"] >= 0
    assert isinstance(data["nutrient_stress_flag"], bool)
    assert isinstance(data["labor_shortfall_flag"], bool)


def assert_round_then_sum_baseline(cycle: dict) -> None:
    """baseline_total_yield_lbs is the sum of the already-rounded weekly figures."""
    weekly = cycle["expected_weekly_yield_lbs"]
    assert round(sum(weekly), 2) == pytest.approx(
        cycle["baseline_total_yield_lbs"], abs=0.001
    ), (
        "baseline_total_yield_lbs must equal the sum of the rounded weekly figures, "
        f"got {cycle['baseline_total_yield_lbs']} for {weekly}"
    )


# --------------------------------------------------------------------------
# Climate strategy
# --------------------------------------------------------------------------


def assert_climate_strategy(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert data["regime"] in ("DAY", "NIGHT")
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "EXPIRED", "CANCELLED")
    assert 5 <= data["temp_setpoint_c"] <= 35
    assert 40 <= data["rh_setpoint_pct"] <= 95
    assert 400 <= data["co2_setpoint_ppm"] <= 1200
    assert 0 <= data["screen_position_pct"] <= 100
    assert data["lighting_hours"] >= 0
    assert data["planned_heat_kwh"] >= 0
    assert data["planned_light_kwh"] >= 0
    assert data["planned_co2_kg"] >= 0
    assert_cost_precision(data["projected_energy_cost_usd"])


# --------------------------------------------------------------------------
# Fertigation
# --------------------------------------------------------------------------


def assert_fertigation_batch(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert data["status"] in ("MIXED", "DELIVERED", "RECONCILED", "DISCARDED")
    assert 100 <= data["planned_volume_liters"] <= 200000
    assert 0 <= data["requested_recirculated_liters"] <= data["planned_volume_liters"]
    assert 0 <= data["reservoir_ec_ms"] <= 12
    assert 0 < data["target_ec_ms"] <= 6
    assert 4.5 <= data["target_ph"] <= 7.0
    assert 10 <= data["drain_target_pct"] <= 45
    assert data["recirc_cap_pct"] in (0, 40, 60)
    assert (
        data["fresh_liters_applied"] + data["recirculated_liters_applied"]
        == data["planned_volume_liters"]
    ), "fresh plus recirculated applied volume must equal the planned volume"
    assert isinstance(data["drain_alarm"], bool)


# --------------------------------------------------------------------------
# Scouting and biological control
# --------------------------------------------------------------------------


def assert_scouting_observation(data: dict) -> None:
    assert_immutable_common_fields(data)
    assert data["pest_code"] in ("WHITEFLY", "THRIPS", "SPIDER_MITE", "APHID")
    assert data["plants_inspected"] >= 1
    assert data["pest_count_per_plant"] >= 0
    assert data["threshold_status"] in ("BELOW", "AT", "ABOVE")
    assert isinstance(data["release_required"], bool)
    assert data["release_required"] == (data["threshold_status"] in ("AT", "ABOVE")), (
        "release_required is true exactly when threshold_status is AT or ABOVE"
    )
    assert is_valid_uuid(data.get("observed_by_worker_id", ""))


def assert_bio_control_release(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert data["agent_code"] in ("ENCARSIA", "AMBLYSEIUS", "APHIDIUS")
    assert data["status"] in (
        "REQUESTED",
        "APPROVED",
        "RELEASED",
        "REJECTED",
        "CANCELLED",
    )
    assert data["planned_release_count"] >= 100
    assert 0 <= data["revision_count"] <= 2


# --------------------------------------------------------------------------
# Workers and labor
# --------------------------------------------------------------------------


def assert_worker(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert data["skill"] in ("DELEAF", "TRELLIS", "HARVEST", "SCOUT")
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert data["hourly_rate_usd"] > 0
    assert 0.5 <= data["productivity_index"] <= 2.0
    assert data["committed_hours"] >= 0


def assert_labor_task(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert data["task_type"] in ("DELEAF", "TRELLIS", "HARVEST")
    assert data["status"] in (
        "SCHEDULED",
        "IN_PROGRESS",
        "COMPLETED",
        "CANCELLED",
        "NO_SHOW",
    )
    assert data["planned_units"] > 0
    assert data["standard_units_per_hour"] > 0
    assert data["planned_hours"] > 0
    assert_cost_precision(data["planned_cost_usd"])


# --------------------------------------------------------------------------
# Harvest lots
# --------------------------------------------------------------------------


def assert_harvest_lot(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert data["grading_status"] in ("UNGRADED", "GRADED", "REGRADED")
    assert data["cold_chain_status"] in (
        "AMBIENT",
        "PRECOOLED",
        "COLD_HELD",
        "RELEASED",
        "REJECTED",
    )
    assert data["gross_weight_lbs"] > 0
    assert data["regrade_count"] >= 0


def assert_lot_grade_pools_conserved(lot: dict) -> None:
    """grade_a_lbs equals allocated_a_lbs plus available_a_lbs; likewise for grade B."""
    if lot.get("grade_a_lbs") is not None:
        assert lot["allocated_a_lbs"] + lot["available_a_lbs"] == pytest.approx(
            lot["grade_a_lbs"], abs=0.01
        ), (
            f"grade A pounds must be conserved: {lot['allocated_a_lbs']} + "
            f"{lot['available_a_lbs']} != {lot['grade_a_lbs']}"
        )
    if lot.get("grade_b_lbs") is not None:
        assert lot["allocated_b_lbs"] + lot["available_b_lbs"] == pytest.approx(
            lot["grade_b_lbs"], abs=0.01
        ), (
            f"grade B pounds must be conserved: {lot['allocated_b_lbs']} + "
            f"{lot['available_b_lbs']} != {lot['grade_b_lbs']}"
        )


def assert_mass_balance(lot: dict) -> None:
    """grade_a_lbs, grade_b_lbs and cull_lbs sum to exactly gross_weight_lbs."""
    total = lot["grade_a_lbs"] + lot["grade_b_lbs"] + lot["cull_lbs"]
    assert total == pytest.approx(lot["gross_weight_lbs"], abs=0.01), (
        f"grade split {total} must equal gross weight {lot['gross_weight_lbs']}"
    )


# --------------------------------------------------------------------------
# Commercial end
# --------------------------------------------------------------------------


def assert_retail_program(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert data["grade_spec"] in ("A_ONLY", "A_AND_B")
    assert data["status"] in ("ACTIVE", "PAUSED")
    assert data["weekly_commitment_lbs"] > 0
    assert data["price_per_lb_usd"] > 0
    assert data["shortfall_penalty_per_lb_usd"] >= 0
    assert 1 <= data["priority_rank"] <= 99
    assert data["at_risk_week_count"] >= 0
    assert_cost_precision(data["penalty_accrued_usd"])


def assert_commitment_week(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert data["status"] in (
        "OPEN",
        "ALLOCATED",
        "SHIPPED",
        "CLOSED_FULFILLED",
        "CLOSED_SHORT",
    )
    assert data["committed_lbs"] > 0
    assert data["allocated_lbs"] >= 0
    assert data["shipped_lbs"] >= 0
    assert data["fill_rate_pct"] >= 0
    assert data["provisional_shortfall_lbs"] >= 0
    assert_cost_precision(data["provisional_penalty_usd"])


def assert_lot_allocation(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert data["grade"] in ("A", "B")
    assert data["status"] in ("PROVISIONAL", "CONFIRMED", "RELEASED", "REVOKED")
    assert data["allocated_lbs"] > 0


def assert_money(actual, expected, label: str = "amount") -> None:
    assert actual == pytest.approx(expected, abs=0.01), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_four_decimal_places(value, expected, label: str = "value") -> None:
    assert value == pytest.approx(expected, abs=0.00005), (
        f"{label}: expected {expected}, got {value}"
    )


def assert_three_decimal_places(value, expected, label: str = "value") -> None:
    assert value == pytest.approx(expected, abs=0.0005), (
        f"{label}: expected {expected}, got {value}"
    )
