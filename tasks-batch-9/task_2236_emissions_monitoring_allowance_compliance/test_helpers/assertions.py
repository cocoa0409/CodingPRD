"""Entity assertions and domain invariant checkers."""
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AllowanceAccountStatus,
    AveragingBasis,
    CalStatus,
    CalibrationResult,
    CertificationStatus,
    CompliancePosture,
    ControlOutageStatus,
    ControlStatus,
    DataQuality,
    DispatchState,
    EvaluationStatus,
    EvaluationStatus as _EvaluationStatus,
    ExcessEventStatus,
    FacilityStatus,
    FuelSampleStatus,
    HeatInputMethod,
    LimitUnits,
    MonitoredParameter,
    Pollutant,
    PrimaryFuel,
    QaStatus,
    QuarterlyReportStatus,
    RaBasis,
    RataTestStatus,
    SubstitutionMethod,
    SystemType,
    TransactionOrigin,
    TransactionStatus,
    TransactionType,
)

APPEND_ONLY_FORBIDDEN_FIELDS = ("updated_at", "version")


# --------------------------------------------------------------------------
# Generic shape helpers
# --------------------------------------------------------------------------
def assert_audit_fields(data: Dict[str, Any]) -> None:
    """`id`, `created_at`, `updated_at` and `version` of a mutable resource."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def assert_append_only_audit_fields(data: Dict[str, Any]) -> None:
    """An append-only ledger entry carries only `id` and `created_at`."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    for field in APPEND_ONLY_FORBIDDEN_FIELDS:
        assert field not in data or data[field] is None, (
            f"append-only records carry no {field}; got {data.get(field)!r}"
        )


def decimal_places(value: float) -> int:
    """Number of digits after the decimal point in the serialised value."""
    text = format(Decimal(str(value)).normalize(), "f")
    return len(text.split(".")[1]) if "." in text else 0


def assert_decimal_places(value: Optional[float], places: int, label: str) -> None:
    if value is None:
        return
    assert decimal_places(value) <= places, (
        f"{label} must carry at most {places} decimal places, got {value}"
    )


def assert_whole_tons(value: Any, label: str) -> None:
    assert isinstance(value, int) or float(value).is_integer(), (
        f"{label} is a whole integer, never fractional; got {value}"
    )


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------
def assert_facility(data: Dict[str, Any]) -> None:
    assert_audit_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["orispl_code"], str) and 1 <= len(data["orispl_code"]) <= 8
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["state_code"].isupper(), "state_code is two uppercase letters"
    assert isinstance(data["operator_org"], str) and data["operator_org"]
    assert isinstance(data["programs"], list) and len(data["programs"]) >= 1
    assert is_iso8601_timestamp(data["true_up_deadline_utc"])
    assert isinstance(data["max_concurrent_control_outages"], int)
    assert data["status"] in [s.value for s in FacilityStatus]
    assert data["compliance_posture"] in [p.value for p in CompliancePosture]


def assert_unit(data: Dict[str, Any]) -> None:
    assert_audit_fields(data)
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["unit_identifier"], str) and data["unit_identifier"]
    assert data["primary_fuel"] in [f.value for f in PrimaryFuel]
    assert data["nameplate_capacity_mw"] > 0
    assert data["max_rated_heat_input_mmbtu_hr"] > 0
    assert data["control_status"] in [c.value for c in ControlStatus]
    assert data["dispatch_state"] in [d.value for d in DispatchState]
    assert isinstance(data["dispatch_restricted"], bool)
    assert 0.0 <= data["data_availability_pct"] <= 100.0
    assert_decimal_places(data["data_availability_pct"], 1, "data_availability_pct")
    assert_decimal_places(data["certified_so2_lbs_ytd"], 1, "certified_so2_lbs_ytd")


def assert_monitoring_system(data: Dict[str, Any]) -> None:
    assert_audit_fields(data)
    assert is_valid_uuid(data["unit_id"])
    assert data["parameter"] in [p.value for p in MonitoredParameter]
    assert data["system_type"] in [t.value for t in SystemType]
    assert data["span_value"] > 0
    assert data["qa_status"] in [s.value for s in QaStatus]
    assert data["cal_status"] in [s.value for s in CalStatus]
    assert isinstance(data["consecutive_failed_calibrations"], int)
    assert data["consecutive_failed_calibrations"] >= 0
    assert_decimal_places(data["bias_adjustment_factor"], 4, "bias_adjustment_factor")


def assert_daily_calibration(data: Dict[str, Any]) -> None:
    assert_append_only_audit_fields(data)
    assert is_valid_uuid(data["monitoring_system_id"])
    assert is_iso8601_timestamp(data["calibration_utc"])
    assert_decimal_places(data["zero_error_pct_of_span"], 2, "zero_error_pct_of_span")
    assert_decimal_places(data["span_error_pct_of_span"], 2, "span_error_pct_of_span")
    assert data["result"] in [r.value for r in CalibrationResult]
    assert isinstance(data["monitoring_system_version_after"], int)
    assert data["monitoring_system_version_after"] >= 2, (
        "monitoring_system_version_after is always at least 2, got "
        f"{data['monitoring_system_version_after']}"
    )


def assert_rata_test(data: Dict[str, Any]) -> None:
    assert_audit_fields(data)
    assert is_valid_uuid(data["monitoring_system_id"])
    assert is_iso8601_timestamp(data["window_start_utc"])
    assert is_iso8601_timestamp(data["window_end_utc"])
    assert data["status"] in [s.value for s in RataTestStatus]
    assert data["ra_basis"] in [b.value for b in RaBasis]
    assert isinstance(data["run_count"], int) and data["run_count"] >= 0
    assert isinstance(data["attempt_number"], int) and data["attempt_number"] >= 1
    assert isinstance(data["bias_test_failed"], bool)
    for field in ("reference_mean", "cems_mean", "mean_difference",
                  "confidence_coefficient", "bias_adjustment_factor"):
        assert_decimal_places(data.get(field), 4, field)
    assert_decimal_places(data.get("relative_accuracy_pct"), 1, "relative_accuracy_pct")


def assert_operating_hour(data: Dict[str, Any]) -> None:
    assert_append_only_audit_fields(data)
    assert is_valid_uuid(data["unit_id"])
    assert is_valid_uuid(data["quarterly_report_id"])
    assert is_iso8601_timestamp(data["hour_begin_utc"])
    assert 0.0 <= data["op_time_fraction"] <= 1.0
    assert data["heat_input_method"] in [m.value for m in HeatInputMethod]
    assert data["data_quality"] in [q.value for q in DataQuality]
    assert data["substitution_method"] in [m.value for m in SubstitutionMethod]
    assert_decimal_places(data.get("heat_input_mmbtu"), 3, "heat_input_mmbtu")
    assert_decimal_places(data.get("so2_mass_lbs"), 1, "so2_mass_lbs")
    assert_decimal_places(data.get("nox_mass_lbs"), 1, "nox_mass_lbs")
    assert_decimal_places(data.get("co2_mass_tons"), 3, "co2_mass_tons")
    assert isinstance(data["quarterly_report_version_after"], int)
    assert data["quarterly_report_version_after"] >= 2, (
        "quarterly_report_version_after is always at least 2, got "
        f"{data['quarterly_report_version_after']}"
    )
    if data["data_quality"] == DataQuality.UNAVAILABLE.value:
        assert data.get("so2_mass_lbs") is None, (
            "an UNAVAILABLE hour carries a null so2_mass_lbs"
        )


def assert_fuel_sample(data: Dict[str, Any]) -> None:
    assert_audit_fields(data)
    assert is_valid_uuid(data["unit_id"])
    assert is_iso8601_timestamp(data["sample_utc"])
    assert data["fuel_type"] in [f.value for f in PrimaryFuel]
    assert isinstance(data["lot_identifier"], str) and data["lot_identifier"]
    assert data["status"] in [s.value for s in FuelSampleStatus]


def assert_quarterly_report(data: Dict[str, Any]) -> None:
    assert_audit_fields(data)
    assert is_valid_uuid(data["unit_id"])
    assert isinstance(data["year"], int) and data["year"] >= 2000
    assert data["quarter"] in (1, 2, 3, 4)
    assert data["status"] in [s.value for s in QuarterlyReportStatus]
    for field in ("operating_hour_count", "measured_hour_count",
                  "substituted_hour_count", "resubmission_count"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert 0.0 <= data["monitor_data_availability_pct"] <= 100.0
    assert_decimal_places(
        data["monitor_data_availability_pct"], 1, "monitor_data_availability_pct"
    )
    assert_decimal_places(data["total_heat_input_mmbtu"], 3, "total_heat_input_mmbtu")
    assert_decimal_places(data["total_so2_lbs"], 1, "total_so2_lbs")
    assert_decimal_places(data["total_nox_lbs"], 1, "total_nox_lbs")
    assert_decimal_places(data["total_co2_tons"], 3, "total_co2_tons")
    assert_decimal_places(data["total_so2_tons"], 3, "total_so2_tons")


def assert_compliance_certification(data: Dict[str, Any]) -> None:
    assert_audit_fields(data)
    assert is_valid_uuid(data["quarterly_report_id"])
    assert isinstance(data["certifier_user_id"], str) and data["certifier_user_id"]
    assert isinstance(data["statement_text"], str) and len(data["statement_text"]) >= 10
    assert data["status"] in [s.value for s in CertificationStatus]
    assert is_iso8601_timestamp(data["signed_utc"])
    assert_decimal_places(
        data["certified_so2_lbs_snapshot"], 1, "certified_so2_lbs_snapshot"
    )


def assert_permit_limit(data: Dict[str, Any]) -> None:
    assert_audit_fields(data)
    assert is_valid_uuid(data["unit_id"])
    assert data["pollutant"] in [p.value for p in Pollutant]
    assert data["limit_value"] > 0
    assert_decimal_places(data["limit_value"], 4, "limit_value")
    assert data["limit_units"] in [u.value for u in LimitUnits]
    assert data["averaging_basis"] in [b.value for b in AveragingBasis]
    assert is_iso8601_timestamp(data["effective_from_utc"])
    assert data["evaluation_status"] in [s.value for s in _EvaluationStatus]
    assert isinstance(data["window_sample_count"], int)
    assert data["window_sample_count"] >= 0


def assert_excess_emission_event(data: Dict[str, Any]) -> None:
    assert_audit_fields(data)
    assert is_valid_uuid(data["permit_limit_id"])
    assert is_valid_uuid(data["unit_id"])
    assert is_iso8601_timestamp(data["detected_utc"])
    for field in ("observed_value", "limit_value_snapshot", "exceedance_magnitude"):
        assert_decimal_places(data[field], 4, field)
    assert_whole_tons(
        data["penalty_allowance_debit_tons"], "penalty_allowance_debit_tons"
    )
    assert data["penalty_allowance_debit_tons"] >= 1, (
        "the floor of one ton means even the smallest exceedance carries a consequence"
    )
    assert data["status"] in [s.value for s in ExcessEventStatus]
    assert isinstance(data["return_count"], int) and data["return_count"] >= 0


def assert_allowance_account(data: Dict[str, Any]) -> None:
    assert_audit_fields(data)
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["compliance_year"], int) and data["compliance_year"] >= 2000
    for field in ("holdings_current_vintage_tons", "holdings_prior_vintage_tons",
                  "holdings_next_vintage_tons", "surrendered_tons",
                  "penalty_deducted_tons", "shortfall_tons"):
        assert_decimal_places(data[field], 3, field)
    assert_whole_tons(data["obligation_tons"], "obligation_tons")
    assert data["status"] in [s.value for s in AllowanceAccountStatus]
    assert data["shortfall_tons"] >= 0.0, "shortfall_tons is floored at 0.0"
    assert data["holdings_current_vintage_tons"] >= 0.0, (
        "only holdings_next_vintage_tons may go negative"
    )
    assert data["holdings_prior_vintage_tons"] >= 0.0, (
        "only holdings_next_vintage_tons may go negative"
    )


def assert_allowance_transaction(data: Dict[str, Any]) -> None:
    assert_audit_fields(data)
    assert is_valid_uuid(data["allowance_account_id"])
    assert data["transaction_type"] in [t.value for t in TransactionType]
    assert data["status"] in [s.value for s in TransactionStatus]
    assert data["origin"] in [o.value for o in TransactionOrigin]
    assert data["quantity_tons"] > 0, "quantity_tons is strictly greater than zero"
    for field in ("quantity_tons", "debited_prior_tons", "debited_current_tons",
                  "debited_next_tons"):
        assert_decimal_places(data[field], 3, field)
    assert isinstance(data["vintage_year"], int)
    assert isinstance(data["allowance_account_version_after"], int)


def assert_control_outage_window(data: Dict[str, Any]) -> None:
    assert_audit_fields(data)
    assert is_valid_uuid(data["unit_id"])
    assert is_iso8601_timestamp(data["start_utc"])
    assert is_iso8601_timestamp(data["end_utc"])
    assert data["start_utc"] < data["end_utc"], "end_utc is strictly later than start_utc"
    assert data["status"] in [s.value for s in ControlOutageStatus]
    assert data["control_device"] in ("SCR", "SNCR", "FGD")


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------
def assert_allowance_quantity_conserved(
    account: Dict[str, Any],
    opening_endowment: float,
    settled_transactions: Iterable[Dict[str, Any]],
) -> None:
    """PRD §2.10 conserved-quantity identity, evaluated over SETTLED rows."""
    buckets = (
        account["holdings_current_vintage_tons"]
        + account["holdings_prior_vintage_tons"]
        + account["holdings_next_vintage_tons"]
    )
    surrendered = sum(
        t["quantity_tons"]
        for t in settled_transactions
        if t["status"] == TransactionStatus.SETTLED.value
        and t["transaction_type"] == TransactionType.SURRENDER.value
    )
    penalties = sum(
        t["quantity_tons"]
        for t in settled_transactions
        if t["status"] == TransactionStatus.SETTLED.value
        and t["transaction_type"] == TransactionType.PENALTY_DEDUCTION.value
    )
    inbound = sum(
        t["quantity_tons"]
        for t in settled_transactions
        if t["status"] == TransactionStatus.SETTLED.value
        and t["transaction_type"]
        in (TransactionType.PURCHASE.value, TransactionType.TRANSFER_IN.value)
    )
    outbound = sum(
        t["quantity_tons"]
        for t in settled_transactions
        if t["status"] == TransactionStatus.SETTLED.value
        and t["transaction_type"] == TransactionType.TRANSFER_OUT.value
    )
    total = buckets + surrendered + penalties - inbound + outbound
    assert abs(total - opening_endowment) < 0.0005, (
        "allowance tonnage is conserved: expected the identity to close at "
        f"{opening_endowment}, got {total}"
    )


def assert_holdings_sum(account: Dict[str, Any], expected: float) -> None:
    total = (
        account["holdings_current_vintage_tons"]
        + account["holdings_prior_vintage_tons"]
        + account["holdings_next_vintage_tons"]
    )
    assert abs(total - expected) < 0.0005, (
        f"holdings buckets should sum to {expected}, got {total}"
    )


def assert_report_hour_partition(report: Dict[str, Any], hours: List[Dict[str, Any]]):
    """Every hour of a report is MEASURED, SUBSTITUTED or UNAVAILABLE, and the
    measured/substituted counts agree with the hour rows."""
    measured = [h for h in hours if h["data_quality"] == DataQuality.MEASURED.value]
    substituted = [
        h for h in hours if h["data_quality"] == DataQuality.SUBSTITUTED.value
    ]
    unavailable = [
        h for h in hours if h["data_quality"] == DataQuality.UNAVAILABLE.value
    ]
    assert len(measured) + len(substituted) + len(unavailable) == len(hours), (
        "data_quality partitions the report's hours"
    )
    assert report["measured_hour_count"] == len(measured), (
        f"measured_hour_count {report['measured_hour_count']} != {len(measured)}"
    )
    assert report["substituted_hour_count"] == len(substituted), (
        f"substituted_hour_count {report['substituted_hour_count']} != "
        f"{len(substituted)}"
    )


def assert_version_bumped_by(before: Dict[str, Any], after: Dict[str, Any], delta: int):
    assert after["version"] == before["version"] + delta, (
        f"expected version {before['version'] + delta}, got {after['version']}"
    )
