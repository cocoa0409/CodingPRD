"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    CompressorStatus,
    ContractTier,
    DisputeStatus,
    FacilityPosture,
    FacilityStatus,
    DemandProfileStatus,
    LeakSeverity,
    LeakSurveyStatus,
    LeakTagStatus,
    MaintenanceComponent,
    MaintenanceScheduleStatus,
    RentalAssetStatus,
    RentalReservationStatus,
    RetrofitProjectStatus,
    SavingsStatus,
    RebateStatus,
    ServiceContractStatus,
    SettlementStatus,
    ServiceCreditStatus,
    ServiceTicketStatus,
    TicketSeverity,
)

# PRD §2.4: created_at / updated_at are ISO 8601 UTC with three fractional digits.
_ISO8601_MILLIS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
# PRD §2.8: dates are ISO YYYY-MM-DD.
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _enum_values(enum_cls):
    return [member.value for member in enum_cls]


def assert_iso8601_millis(value: str, field: str = "timestamp") -> None:
    """Assert ISO 8601 UTC timestamp with exactly three fractional digits (PRD §2.4)."""
    assert isinstance(value, str) and _ISO8601_MILLIS_RE.match(value), (
        f"{field} must be an ISO 8601 UTC timestamp with three fractional digits, "
        f"got {value!r}"
    )


def assert_iso_date(value: str, field: str = "date") -> None:
    assert isinstance(value, str) and _ISO_DATE_RE.match(value), (
        f"{field} must be an ISO YYYY-MM-DD date, got {value!r}"
    )


def _assert_common_fields(data: dict) -> None:
    """PRD §2.4: every resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert_iso8601_millis(data.get("created_at", ""), "created_at")
    assert_iso8601_millis(data.get("updated_at", ""), "updated_at")
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_optional_str(data: dict, field: str) -> None:
    if data.get(field) is not None:
        assert isinstance(data[field], str), f"{field} must be a string when set"


def _assert_optional_int(data: dict, field: str) -> None:
    if data.get(field) is not None:
        assert isinstance(data[field], int), f"{field} must be an integer when set"


def assert_facility(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["utility_rate_cents_per_kwh"], int)
    assert isinstance(data["operating_hours_per_year"], int)
    assert isinstance(data["repair_budget_cents"], int)
    assert data["status"] in _enum_values(FacilityStatus)
    assert data["posture"] in _enum_values(FacilityPosture)
    assert isinstance(data["repair_committed_cents"], int)
    assert isinstance(data["rental_escrow_cents"], int)


def assert_compressor(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("facility_id", ""))
    assert isinstance(data["asset_tag"], str) and len(data["asset_tag"]) > 0
    assert isinstance(data["rated_kw"], int)
    assert isinstance(data["rated_cfm"], int)
    assert isinstance(data["run_hours_total"], int)
    assert data["status"] in _enum_values(CompressorStatus)


def assert_demand_profile(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("facility_id", ""))
    assert_iso_date(data["window_start_date"], "window_start_date")
    assert_iso_date(data["window_end_date"], "window_end_date")
    assert isinstance(data["measured_kwh"], int)
    assert isinstance(data["measured_avg_cfm"], (int, float))
    assert isinstance(data["measured_peak_cfm"], (int, float))
    assert isinstance(data["baseline_annual_kwh"], int)
    assert data["status"] in _enum_values(DemandProfileStatus)
    _assert_optional_str(data, "locked_by_user_id")
    _assert_optional_str(data, "superseded_by_id")


def assert_leak_survey(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("facility_id", ""))
    assert_iso_date(data["survey_date"], "survey_date")
    assert data["status"] in _enum_values(LeakSurveyStatus)
    _assert_optional_str(data, "submitted_by_user_id")
    _assert_optional_str(data, "verified_by_user_id")
    if data.get("total_leak_cfm") is not None:
        assert isinstance(data["total_leak_cfm"], (int, float))
    _assert_optional_int(data, "tag_count")


def assert_leak_tag(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("survey_id", ""))
    assert isinstance(data["location_description"], str)
    assert isinstance(data["cfm_loss"], (int, float))
    assert isinstance(data["repair_quote_cents"], int)
    assert data["status"] in _enum_values(LeakTagStatus)
    if data.get("severity") is not None:
        assert data["severity"] in _enum_values(LeakSeverity)
    _assert_optional_int(data, "priority_rank")
    _assert_optional_int(data, "annual_kwh_savings")
    _assert_optional_str(data, "repaired_by_user_id")


def assert_maintenance_schedule(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("facility_id", ""))
    assert data["component"] in _enum_values(MaintenanceComponent)
    assert isinstance(data["interval_hours"], int) and data["interval_hours"] > 0
    assert isinstance(data["anchor_run_hours"], int)
    assert isinstance(data["next_due_run_hours"], int)
    assert isinstance(data["is_delinquent"], bool)
    assert data["status"] in _enum_values(MaintenanceScheduleStatus)


def assert_retrofit_project(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("facility_id", ""))
    assert isinstance(data["baseline_pressure_psi"], int)
    assert isinstance(data["target_pressure_psi"], int)
    assert isinstance(data["sequence_compressor_ids"], list)
    assert isinstance(data["project_cost_cents"], int)
    assert data["status"] in _enum_values(RetrofitProjectStatus)
    _assert_optional_str(data, "accepted_date")


def assert_savings_case(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("facility_id", ""))
    assert is_valid_uuid(data.get("baseline_profile_id", ""))
    assert isinstance(data["baseline_profile_version"], int)
    assert isinstance(data["baseline_stale"], bool)
    assert is_valid_uuid(data.get("retrofit_project_id", ""))
    assert isinstance(data["retrofit_stale"], bool)
    assert isinstance(data["deemed_annual_savings_kwh"], int)
    _assert_optional_int(data, "measured_annual_savings_kwh")
    _assert_optional_str(data, "post_profile_id")
    assert data["savings_status"] in _enum_values(SavingsStatus)
    assert data["rebate_status"] in _enum_values(RebateStatus)
    _assert_optional_int(data, "provisional_rebate_cents")
    _assert_optional_int(data, "final_rebate_cents")


def assert_service_contract(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("facility_id", ""))
    assert data["tier"] in _enum_values(ContractTier)
    assert_iso_date(data["start_date"], "start_date")
    assert isinstance(data["term_months"], int)
    assert_iso_date(data["end_date"], "end_date")
    assert isinstance(data["monthly_fee_cents"], int)
    assert isinstance(data["sla_base_hours"], int)
    assert data["status"] in _enum_values(ServiceContractStatus)
    assert isinstance(data["sla_breach_count"], int)
    assert isinstance(data["termination_penalty_waived"], bool)
    _assert_optional_int(data, "termination_fee_cents")
    assert isinstance(data["credits_accrued_total_cents"], int)
    assert isinstance(data["credits_applied_total_cents"], int)
    assert isinstance(data["credits_expired_total_cents"], int)
    assert isinstance(data["credits_outstanding_cents"], int)


def assert_service_ticket(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("facility_id", ""))
    assert is_valid_uuid(data.get("contract_id", ""))
    assert is_valid_uuid(data.get("compressor_id", ""))
    assert data["severity"] in _enum_values(TicketSeverity)
    assert is_iso8601_timestamp(data.get("reported_at", ""))
    assert data["sla_tier_snapshot"] in _enum_values(ContractTier)
    assert is_iso8601_timestamp(data.get("sla_deadline", ""))
    if data.get("first_response_at") is not None:
        assert is_iso8601_timestamp(data["first_response_at"])
    if data.get("sla_met") is not None:
        assert isinstance(data["sla_met"], bool)
    assert data["status"] in _enum_values(ServiceTicketStatus)


def assert_rental_asset(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["fleet_tag"], str) and len(data["fleet_tag"]) > 0
    assert isinstance(data["rated_cfm"], int)
    assert isinstance(data["daily_rate_cents"], int)
    assert isinstance(data["deposit_cents"], int)
    assert data["status"] in _enum_values(RentalAssetStatus)
    _assert_optional_str(data, "next_available_date")


def assert_rental_reservation(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("facility_id", ""))
    assert is_valid_uuid(data.get("rental_asset_id", ""))
    assert is_valid_uuid(data.get("down_compressor_id", ""))
    assert_iso_date(data["start_date"], "start_date")
    assert_iso_date(data["end_date"], "end_date")
    assert isinstance(data["planned_days"], int)
    assert isinstance(data["quoted_cents"], int)
    assert isinstance(data["deposit_cents"], int)
    assert data["status"] in _enum_values(RentalReservationStatus)
    _assert_optional_str(data, "actual_return_date")
    _assert_optional_int(data, "actual_bill_cents")
    _assert_optional_int(data, "final_bill_cents")


def assert_guarantee_certificate(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("facility_id", ""))
    assert is_valid_uuid(data.get("contract_id", ""))
    assert is_valid_uuid(data.get("savings_case_id", ""))
    assert isinstance(data["guaranteed_pct"], (int, float))
    assert isinstance(data["guaranteed_kwh"], int)
    assert isinstance(data["deadband_kwh"], int)
    _assert_optional_int(data, "measured_kwh_at_settlement")
    _assert_optional_int(data, "shortfall_kwh")
    _assert_optional_int(data, "payout_cents")
    assert isinstance(data["settlement_blocked"], bool)
    assert data["settlement_status"] in _enum_values(SettlementStatus)
    assert data["dispute_status"] in _enum_values(DisputeStatus)
    _assert_optional_str(data, "dispute_reason")


def assert_service_credit(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("contract_id", ""))
    assert is_valid_uuid(data.get("ticket_id", ""))
    assert data["source"] == "SLA_BREACH"
    assert isinstance(data["amount_cents"], int)
    assert is_iso8601_timestamp(data.get("accrued_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))
    assert data["status"] in _enum_values(ServiceCreditStatus)


def assert_credit_partition_identity(contract: dict) -> None:
    """PRD §3.7: credits_accrued_total_cents always equals credits_applied_total_cents
    plus credits_expired_total_cents plus credits_outstanding_cents."""
    accrued = contract["credits_accrued_total_cents"]
    applied = contract["credits_applied_total_cents"]
    expired = contract["credits_expired_total_cents"]
    outstanding = contract["credits_outstanding_cents"]
    assert accrued == applied + expired + outstanding, (
        f"credit partition identity violated: accrued {accrued} != "
        f"applied {applied} + expired {expired} + outstanding {outstanding}"
    )
