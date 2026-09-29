"""Resource assertions and domain invariant checkers drawn from the PRD."""
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    CASE_TYPES,
    CLIMATE_ZONES,
    DISPOSITIONS,
    EQUIPMENT_CLASSES,
    FAULT_SEVERITIES,
    LIGHTING_ZONES,
    MEASURE_TYPES,
    OVERRIDE_TYPES,
    PRODUCT_CLASSES,
    RATE_FAMILIES,
    SEASONS,
    STORE_FORMATS,
)


def assert_common_fields(data: dict):
    """id, created_at, updated_at and version are carried by every resource
    except the append-only demand interval."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_event_row_fields(data: dict):
    """An append-only event row carries only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "an append-only interval carries no version counter"
    assert "updated_at" not in data, "an append-only interval carries no updated_at"


def assert_id_has_no_prefix(value: str):
    assert is_valid_uuid(value), f"resource ids are bare UUIDs, got {value!r}"


def assert_store(data: dict):
    assert_common_fields(data)
    assert isinstance(data["code"], str) and 1 <= len(data["code"]) <= 32
    assert data["climate_zone"] in CLIMATE_ZONES
    assert data["store_format"] in STORE_FORMATS
    assert isinstance(data["floor_area_sqft"], int) and data["floor_area_sqft"] > 0
    assert data["bms_status"] in ["NOT_DEPLOYED", "COMMISSIONING", "ACTIVE", "DEGRADED"]
    assert data["energy_posture"] in ["NORMAL", "CONSTRAINED", "CURTAILED", "LOCKED"]
    assert data["override_kwh_used_month"] >= 0
    assert data["verified_savings_kwh_ytd"] >= 0
    assert data["alarm_case_count"] >= 0
    assert data["urgent_work_order_count"] >= 0
    assert isinstance(data["benchmark_outlier_flag"], bool)


def assert_setpoint_standard(data: dict):
    assert_common_fields(data)
    assert data["climate_zone"] in CLIMATE_ZONES
    assert data["store_format"] in STORE_FORMATS
    assert data["season"] in SEASONS
    assert 60.0 <= data["cooling_setpoint_f"] <= 85.0
    assert 55.0 <= data["heating_setpoint_f"] <= 78.0
    assert data["heating_setpoint_f"] < data["cooling_setpoint_f"]
    assert data["deadband_f"] >= 1.0
    assert data["lighting_lux_target"] > 0
    assert data["status"] in ["DRAFT", "PUBLISHED", "SUPERSEDED"]
    assert isinstance(data["revision"], int) and data["revision"] >= 1


def assert_utility_account(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["store_id"])
    assert data["rate_family"] in RATE_FAMILIES
    assert data["demand_charge_per_kw"] > 0
    assert data["rate_on_peak"] > 0 and data["rate_off_peak"] > 0
    assert data["ratchet_peak_kw"] >= 0
    assert data["tariff_state"] in ["STABLE", "PENDING_SWITCH", "SWITCHED"]
    assert data["dr_enrollment_state"] in ["ENROLLED", "SUSPENDED"]
    assert data["dr_optout_count"] >= 0
    assert_cost_precision(data["dr_incentive_accrued_usd"])


def assert_demand_interval(data: dict):
    assert_event_row_fields(data)
    assert is_valid_uuid(data["utility_account_id"])
    assert is_iso8601_timestamp(data["interval_start_iso"])
    assert data["kw_demand"] >= 0
    assert isinstance(data["is_on_peak"], bool)
    assert isinstance(data["is_dr_event_day"], bool)


def assert_utility_bill(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["utility_account_id"])
    assert data["validation_state"] in [
        "RECEIVED",
        "VALIDATED",
        "VARIANCE_FLAGGED",
        "DISPUTED",
        "ADJUSTED",
    ]
    for field in ("on_peak_kwh", "off_peak_kwh", "billed_kwh", "billed_peak_kw"):
        assert data[field] >= 0, f"{field} must be non-negative"
    assert data["billed_amount_usd"] >= 0
    if data.get("peak_basis") is not None:
        assert data["peak_basis"] in ["COINCIDENT_PEAK", "ANYTIME_PEAK"]


def assert_bill_is_unrecomputed(data: dict):
    """A bill in RECEIVED carries every derived field null."""
    for field in (
        "recomputed_energy_cost_usd",
        "recomputed_demand_cost_usd",
        "recomputed_rider_cost_usd",
        "recomputed_surcharge_usd",
        "recomputed_amount_usd",
        "billable_demand_kw",
        "peak_basis",
        "variance_pct",
    ):
        assert data[field] is None, f"{field} must be null before a recompute"


def assert_demand_response_event(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["utility_account_id"])
    assert data["event_state"] in [
        "SCHEDULED",
        "NOTIFIED",
        "ACTIVE",
        "COMPLETED",
        "OPTED_OUT",
    ]
    assert data["settlement_state"] in ["PENDING", "SETTLED", "REVERSED"]
    assert data["target_reduction_kw"] > 0
    assert_cost_precision(data["incentive_usd"])
    assert_cost_precision(data["penalty_usd"])


def assert_refrigeration_case(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["store_id"])
    assert data["case_type"] in CASE_TYPES
    assert data["product_class"] in PRODUCT_CLASSES
    assert data["alarm_high_f"] > data["alarm_low_f"]
    assert data["product_value_usd"] >= 0
    assert data["monitoring_state"] in ["ARMED", "ALARM", "BYPASSED"]
    assert data["consecutive_breach_count"] >= 0


def assert_temp_excursion(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["case_id"])
    assert data["state"] in [
        "OPEN",
        "ACKNOWLEDGED",
        "ESCALATED",
        "DISPOSITION_REQUIRED",
        "CLOSED",
    ]
    assert data["mandatory_disposition"] in ["NONE", "DISCARD"]
    assert data["exposure_minutes"] >= 0
    if data.get("disposition") is not None:
        assert data["disposition"] in DISPOSITIONS


def assert_lighting_override(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["store_id"])
    assert data["zone"] in LIGHTING_ZONES
    assert data["override_type"] in OVERRIDE_TYPES
    assert data["zone_load_kw"] > 0
    assert data["state"] in ["SCHEDULED", "ACTIVE", "EXPIRED", "REVOKED"]
    assert_cost_precision(data["projected_kwh"])
    if data.get("revoke_source") is not None:
        assert data["revoke_source"] in ["USER", "SYSTEM_POSTURE"]


def assert_fault_diagnostic(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["store_id"])
    assert data["equipment_class"] in EQUIPMENT_CLASSES
    assert data["severity"] in FAULT_SEVERITIES
    assert data["occurrence_count"] >= 1
    assert data["affected_load_kw"] >= 0
    assert 0.0 <= data["fault_score"] <= 100.0, "fault_score is capped at 100.0"
    assert data["state"] in ["DETECTED", "TRIAGED", "SUPPRESSED", "RESOLVED"]
    assert is_iso8601_timestamp(data["detected_at_iso"])


def assert_work_order(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["fault_id"])
    assert data["priority"] in ["URGENT", "ROUTINE"]
    assert data["state"] in ["OPEN", "SCHEDULED", "COMPLETED"]


def assert_retrofit_project(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["store_id"])
    assert data["measure_type"] in MEASURE_TYPES
    assert data["capex_usd"] > 0
    assert data["projected_annual_savings_kwh"] > 0
    assert data["priority_basis"] in ["SIMPLE_PAYBACK", "RISK_ADJUSTED"]
    assert data["state"] in [
        "PROPOSED",
        "APPROVED",
        "REJECTED",
        "VERIFIED",
        "SHORTFALL_REVIEW",
    ]
    assert 0.0 <= data["priority_score"] <= 100.0, "priority_score is clamped to 0..100"
    assert isinstance(data["escalated_review"], bool)


# ----------------------------------------------------------------------
# Domain invariants
# ----------------------------------------------------------------------
def assert_posture_ladder_consistent(store: dict, has_escalated_excursion: bool,
                                     has_active_event: bool, constrained_input: bool):
    """The posture ladder is evaluated first match wins."""
    if has_escalated_excursion:
        expected = "LOCKED"
    elif has_active_event:
        expected = "CURTAILED"
    elif constrained_input:
        expected = "CONSTRAINED"
    else:
        expected = "NORMAL"
    assert store["energy_posture"] == expected, (
        f"expected posture {expected}, got {store['energy_posture']}"
    )


def assert_incentive_ledger_identity(account: dict, settled_incentives: list):
    """dr_incentive_accrued_usd equals the sum of incentive_usd over the
    account's events whose settlement_state is SETTLED."""
    expected = round(sum(settled_incentives), 2)
    assert abs(account["dr_incentive_accrued_usd"] - expected) < 0.005, (
        f"incentive ledger {account['dr_incentive_accrued_usd']} != {expected}"
    )


def assert_savings_ledger_identity(store: dict, verified_measured_savings: list):
    """verified_savings_kwh_ytd equals the sum of measured_savings_kwh over
    the store's projects in VERIFIED."""
    expected = round(sum(verified_measured_savings), 2)
    assert abs(store["verified_savings_kwh_ytd"] - expected) < 0.005, (
        f"savings ledger {store['verified_savings_kwh_ytd']} != {expected}"
    )


def assert_envelope_meta(response_json: dict, is_list: bool = False):
    meta = response_json["meta"]
    assert meta["api_request_id"].startswith("req_"), "api_request_id carries a req_ prefix"
    assert is_iso8601_timestamp(meta["api_request_timestamp"])
    if is_list:
        for key in ("limit", "offset", "total_count", "has_more"):
            assert key in meta, f"a list envelope reports {key}"
    assert response_json["response_type"] in ["object", "array", "error"]
