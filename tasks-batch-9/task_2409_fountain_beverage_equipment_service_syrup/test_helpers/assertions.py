"""Entity shape assertions and domain invariant checkers.

Every check below restates a rule the PRD makes explicit: the common
properties carried by ten of the eleven resource kinds, the single immutable
kind that carries neither ``updated_at`` nor ``version``, the two conserved
ledgers, and the service-posture recomputation bands.
"""

import math

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    BRIX_TARGET_RATIO,
    BRIX_TOLERANCE,
    CRITICAL_AT,
    CRITICAL_COVER_DAYS,
    FROZEN_OVERDUE_AT,
    HARDNESS_BASELINE_GPG,
    HARDNESS_DERATE_PER_GPG,
    LOW_COVER_DAYS,
    OUNCES_PER_GALLON,
    POSTURE_ADD,
    RESTRICTED_OVERDUE_AT,
    SCORE_CAP,
    SYMPTOM_WEIGHT,
    CALIBRATION_ADD,
    OVERDUE_ADD_CAP,
    OVERDUE_ADD_PER_TASK,
    TIER_FACTOR,
    URGENT_AT,
)


# ─── Generic helpers ──────────────────────────────────────────────────────


def round_half_up(value: float, places: int = 0) -> float:
    """Half-up rounding, the tie-breaking direction the PRD names."""
    factor = 10 ** places
    scaled = value * factor
    # Nudge away from binary-representation shortfalls before flooring.
    result = math.floor(scaled + 0.5 + 1e-9)
    return result / factor if places else float(result)


def assert_common_fields(data: dict):
    """The properties the PRD gives to every resource kind except TelemetryReading."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_immutable_common_fields(data: dict):
    """The reduced property set the PRD reserves for TelemetryReading."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "TelemetryReading carries no updated_at"
    assert "version" not in data, "TelemetryReading carries no version"


def assert_envelope_meta(body: dict):
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), "api_request_id must start with req_"
    assert is_iso8601_timestamp(meta["api_request_timestamp"])


# ─── Per-entity assertions ────────────────────────────────────────────────


def assert_outlet(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["account_code"], str) and data["account_code"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert data["throughput_tier"] in ("SMALL", "MEDIUM", "LARGE")
    assert 0 <= data["water_hardness_gpg"] <= 60
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert data["service_posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert isinstance(data["open_compliance_hold_count"], int)
    assert data["open_compliance_hold_count"] >= 0
    assert isinstance(data["overdue_task_count"], int)
    assert data["overdue_task_count"] >= 0
    assert_posture_matches_counters(data)


def assert_agreement(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["outlet_id"])
    assert is_iso8601_timestamp(data["term_start_date"])
    assert is_iso8601_timestamp(data["term_end_date"])
    assert data["annual_commitment_gallons"] > 0
    assert data["equipment_value_cents"] > 0
    assert isinstance(data["free_on_loan"], bool)
    assert data["shortfall_fee_cents_per_gallon"] >= 0
    assert data["status"] in (
        "DRAFT",
        "ACTIVE",
        "SHORTFALL_REVIEW",
        "RECALL_PENDING",
        "TERMINATED",
        "EXPIRED",
    )
    assert data["exposure_variant"] in ("BOOK_VALUE", "REPLACEMENT_RISK")
    assert data["assessed_shortfall_gallons"] >= 0
    assert data["assessed_fee_cents"] >= 0


def assert_dispenser_unit(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["outlet_id"])
    assert is_valid_uuid(data["agreement_id"])
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert is_iso8601_timestamp(data["installed_at"])
    assert data["status"] in ("IN_SERVICE", "SERVICE_HOLD", "RECALL_STAGED", "RETURNED")
    assert data["calibration_status"] in ("UNVERIFIED", "IN_SPEC", "OUT_OF_SPEC")
    assert data["lifetime_dispensed_gallons"] >= 0
    assert data["gallons_at_last_filter_change"] >= 0


def assert_supply_item(data: dict):
    assert_common_fields(data)
    assert isinstance(data["sku_code"], str) and data["sku_code"]
    assert isinstance(data["brand_name"], str) and data["brand_name"]
    assert data["supply_form"] in ("CARTRIDGE", "BAG_IN_BOX")
    assert data["case_pack_units"] >= 1
    assert data["ounces_per_unit"] > 0
    assert isinstance(data["promotional"], bool)
    assert data["national_allocation_units"] >= 0
    assert data["reserved_pool_units"] >= 0


def assert_telemetry_reading(data: dict):
    assert_immutable_common_fields(data)
    assert is_valid_uuid(data["dispenser_unit_id"])
    assert is_valid_uuid(data["supply_item_id"])
    assert data["dispensed_ounces"] >= 0
    assert is_iso8601_timestamp(data["reading_at"])
    assert 1 <= data["window_days"] <= 90
    assert data["source"] in ("TELEMETRY", "MANUAL_AUDIT")


def assert_supply_position(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["outlet_id"])
    assert is_valid_uuid(data["supply_item_id"])
    assert data["on_hand_units"] >= 0
    assert data["forecast_variant"] in ("TRAILING_ACTUAL", "THROUGHPUT_PROJECTED")
    assert data["forecast_units"] >= 0
    assert data["requested_units"] >= 0
    assert data["allocated_units"] >= 0
    assert data["alert_level"] in ("NONE", "LOW", "CRITICAL")
    assert isinstance(data["promo_suppressed"], bool)


def assert_route(data: dict):
    assert_common_fields(data)
    assert isinstance(data["route_code"], str) and data["route_code"]
    assert isinstance(data["depot_region_code"], str) and data["depot_region_code"]
    assert is_iso8601_timestamp(data["service_date"])
    assert isinstance(data["van_code"], str) and data["van_code"]
    assert data["capacity_units"] >= 1
    assert data["status"] in ("PLANNED", "DISPATCHED", "COMPLETED", "CANCELLED")
    assert data["committed_units"] >= 0
    assert data["delivered_units"] >= 0


def assert_route_stop(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["route_id"])
    assert is_valid_uuid(data["outlet_id"])
    assert data["sequence_index"] >= 1
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in ("PENDING", "ARRIVED", "SERVED", "SKIPPED")
    assert data["delivered_units"] >= 0
    assert data["skip_reason_code"] in (
        None,
        "OUTLET_CLOSED",
        "POSTURE_FROZEN",
        "ACCESS_DENIED",
    )


def assert_maintenance_task(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["dispenser_unit_id"])
    assert data["task_type"] in (
        "PREVENTIVE",
        "BRIX_CALIBRATION",
        "SANITATION",
        "FILTER_CHANGE",
    )
    assert is_iso8601_timestamp(data["due_at"])
    assert data["status"] in ("SCHEDULED", "DUE", "OVERDUE", "COMPLETED", "WAIVED")
    assert data["breach_kind"] in (None, "DATE", "GALLON")
    assert data.get("calibration_outcome") in (None, "PASS", "FAIL")


def assert_service_call(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["dispenser_unit_id"])
    assert is_iso8601_timestamp(data["reported_at"])
    assert data["symptom_code"] in (
        "NO_POUR",
        "OFF_RATIO",
        "LEAK",
        "CO2_LOW",
        "ICE_FAULT",
    )
    assert 0 <= data["severity_score"] <= SCORE_CAP
    assert data["severity"] in ("ROUTINE", "URGENT", "CRITICAL")
    assert data["status"] in (
        "OPEN",
        "DISPATCHED",
        "ON_SITE",
        "RESOLVED",
        "ESCALATED",
        "CANCELLED",
    )
    assert data["reserved_part_units"] >= 0
    assert data["consumed_part_units"] >= 0
    assert 0 <= data["escalation_count"] <= 2
    assert data["resolution_code"] in (
        None,
        "PART_REPLACED",
        "CALIBRATED",
        "CLEANED",
        "NO_FAULT_FOUND",
    )
    assert_severity_band_matches_score(data)


def assert_van_part_stock(data: dict):
    assert_common_fields(data)
    assert isinstance(data["van_code"], str) and data["van_code"]
    assert isinstance(data["part_sku"], str) and data["part_sku"]
    assert data["on_van_units"] >= 0
    assert data["reserved_units"] >= 0
    assert data["consumed_units"] >= 0
    assert data["initial_units"] >= 0
    assert data["restocked_units"] >= 0
    assert_van_parts_conserved(data)


def assert_brand_mix_report(data: dict):
    assert is_valid_uuid(data["outlet_id"])
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert data["total_ounces"] >= 0
    assert isinstance(data["lines"], list)
    assert isinstance(data["promo_available_skus"], list)
    for line in data["lines"]:
        assert is_valid_uuid(line["supply_item_id"])
        assert isinstance(line["sku_code"], str)
        assert isinstance(line["brand_name"], str)
        assert line["total_ounces"] >= 0


def assert_allocation_summary(data: dict, stop_id: str):
    assert data["route_stop_id"] == stop_id
    assert isinstance(data["allocated_position_count"], int)
    assert isinstance(data["total_allocated_units"], int)
    assert isinstance(data["granted_units_by_position"], dict)


# ─── Domain invariants ────────────────────────────────────────────────────


def assert_posture_matches_counters(outlet: dict):
    """Recompute ``service_posture`` from the outlet's two counters, first match wins."""
    if outlet["open_compliance_hold_count"] >= 1 or (
        outlet["overdue_task_count"] >= FROZEN_OVERDUE_AT
    ):
        expected = "FROZEN"
    elif outlet["overdue_task_count"] >= RESTRICTED_OVERDUE_AT:
        expected = "RESTRICTED"
    else:
        expected = "OPEN"
    assert outlet["service_posture"] == expected, (
        f"service_posture {outlet['service_posture']} does not follow from "
        f"holds={outlet['open_compliance_hold_count']} "
        f"overdue={outlet['overdue_task_count']} (expected {expected})"
    )


def assert_van_parts_conserved(stock: dict):
    """``on_van_units + reserved_units + consumed_units == initial_units + restocked_units``."""
    left = stock["on_van_units"] + stock["reserved_units"] + stock["consumed_units"]
    right = stock["initial_units"] + stock["restocked_units"]
    assert left == right, (
        f"van parts ledger drifted: {stock['on_van_units']} + {stock['reserved_units']}"
        f" + {stock['consumed_units']} != {stock['initial_units']}"
        f" + {stock['restocked_units']}"
    )


def assert_pool_matches_positions(item: dict, positions: list):
    """``SupplyItem.reserved_pool_units == SUM(positions.allocated_units)``."""
    total = sum(p["allocated_units"] for p in positions)
    assert item["reserved_pool_units"] == total, (
        f"reserved_pool_units {item['reserved_pool_units']} != "
        f"sum of allocated_units {total}"
    )


def assert_severity_band_matches_score(call: dict):
    score = call["severity_score"]
    if score >= CRITICAL_AT:
        expected = "CRITICAL"
    elif score >= URGENT_AT:
        expected = "URGENT"
    else:
        expected = "ROUTINE"
    assert call["severity"] == expected, (
        f"severity {call['severity']} does not follow from score {score}"
    )


# ─── Expected-value calculators (PRD formulae, restated for the tests) ────


def expected_severity_score(symptom_code: str, posture: str, overdue_task_count: int,
                            calibration_status: str) -> int:
    score = SYMPTOM_WEIGHT[symptom_code]
    score += POSTURE_ADD[posture]
    score += min(OVERDUE_ADD_PER_TASK * overdue_task_count, OVERDUE_ADD_CAP)
    if calibration_status == "OUT_OF_SPEC":
        score += CALIBRATION_ADD
    return min(score, SCORE_CAP)


def expected_severity_band(score: int) -> str:
    if score >= CRITICAL_AT:
        return "CRITICAL"
    if score >= URGENT_AT:
        return "URGENT"
    return "ROUTINE"


def expected_effective_gallon_interval(gallon_interval: float,
                                       water_hardness_gpg: float) -> float:
    derate = 1 - HARDNESS_DERATE_PER_GPG * max(
        0, water_hardness_gpg - HARDNESS_BASELINE_GPG
    )
    return round_half_up(gallon_interval * derate, 2)


def expected_lifetime_gallons(total_ounces: float) -> float:
    return round_half_up(total_ounces / OUNCES_PER_GALLON, 2)


def expected_forecast_units(total_ounces: float, window_days: int, variant: str,
                            tier: str, ounces_per_unit: float,
                            on_hand_units: int) -> float:
    daily = total_ounces / window_days
    horizon = daily * 14
    if variant == "THROUGHPUT_PROJECTED":
        horizon *= TIER_FACTOR[tier]
    units = horizon / ounces_per_unit - on_hand_units
    return round_half_up(max(0.0, units), 2)


def expected_alert_level(on_hand_units: int, total_ounces: float, window_days: int,
                         ounces_per_unit: float) -> str:
    if on_hand_units == 0:
        return "CRITICAL"
    daily_units = (total_ounces / window_days) / ounces_per_unit
    if daily_units == 0:
        return "NONE"
    cover_days = on_hand_units / daily_units
    if cover_days < CRITICAL_COVER_DAYS:
        return "CRITICAL"
    if cover_days < LOW_COVER_DAYS:
        return "LOW"
    return "NONE"


def expected_brix_outcome(measured_brix_ratio: float) -> str:
    return (
        "PASS"
        if abs(measured_brix_ratio - BRIX_TARGET_RATIO) <= BRIX_TOLERANCE + 1e-9
        else "FAIL"
    )


def expected_granted_units(requested: int, unreserved_pool: int, remaining_capacity: int,
                           case_pack_units: int) -> int:
    smallest = min(requested, unreserved_pool, remaining_capacity)
    return (smallest // case_pack_units) * case_pack_units


def assert_money_cents(value):
    """Cent amounts are whole integers — the PRD keeps every fee in cents."""
    assert isinstance(value, int), f"cent amount must be an integer, got {value!r}"


def assert_two_decimals(value):
    """Gallon and unit figures the PRD pins to two decimal places."""
    assert value == pytest.approx(round(value, 2), abs=1e-9), (
        f"{value!r} carries more than two decimal places"
    )
