"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    BillingStatus,
    BoilOrderStatus,
    CollectionStatus,
    CovenantStatus,
    CycleStatus,
    MemberClass,
    MembershipStatus,
    MeterSize,
    NotificationChannel,
    PaymentStatus,
    PetitionStatus,
    RateScheduleStatus,
    ReadingType,
    ReserveEntryType,
    ResolutionStatus,
    ResolutionType,
    SampleResult,
    ServiceAreaStatus,
    TapStatus,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_ledger(data: dict):
    """Ledger-style records expose id + created_at only (PRD section 2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ledger records must not expose updated_at"
    assert "version" not in data, "ledger records must not expose version"


def _enum_values(enum_cls) -> list:
    return [member.value for member in enum_cls]


def assert_district(data: dict):
    _assert_common(data)
    assert isinstance(data["district_name"], str) and data["district_name"]
    assert isinstance(data["usda_loan_principal_cents"], int)
    assert data["usda_loan_principal_cents"] >= 0
    assert isinstance(data["annual_debt_service_cents"], int)
    assert data["annual_debt_service_cents"] > 0
    assert isinstance(data["reserve_target_cents"], int)
    assert isinstance(data["reserve_balance_cents"], int)
    assert isinstance(data["reserve_deficit_cents"], int)
    assert data["covenant_status"] in _enum_values(CovenantStatus)
    assert data["active_rate_schedule_id"] is None or isinstance(data["active_rate_schedule_id"], str)
    assert isinstance(data["current_billing_epoch"], int)
    assert isinstance(data["boil_order_active"], bool)
    # reserve deficit invariant: max(0, target - balance)
    assert data["reserve_deficit_cents"] == max(
        0, data["reserve_target_cents"] - data["reserve_balance_cents"]
    ), "reserve_deficit_cents must equal max(0, target - balance)"


def assert_service_area(data: dict):
    _assert_common(data)
    assert isinstance(data["area_name"], str) and data["area_name"]
    assert isinstance(data["boundary_acres"], int) and data["boundary_acres"] > 0
    assert data["status"] in _enum_values(ServiceAreaStatus)


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["service_area_id"], str)
    assert data["member_class"] in _enum_values(MemberClass)
    assert data["membership_status"] in _enum_values(MembershipStatus)
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["consecutive_delinquent_cycles"], int)
    assert data["consecutive_delinquent_cycles"] >= 0


def assert_tap(data: dict):
    _assert_common(data)
    assert isinstance(data["member_id"], str)
    assert isinstance(data["tap_fee_cents"], int) and data["tap_fee_cents"] >= 0
    assert isinstance(data["tap_fee_paid_cents"], int) and data["tap_fee_paid_cents"] >= 0
    assert data["meter_size"] in _enum_values(MeterSize)
    assert data["status"] in _enum_values(TapStatus)


def assert_meter_reading(data: dict):
    _assert_ledger(data)
    assert isinstance(data["tap_id"], str)
    assert isinstance(data["cycle_id"], str)
    assert isinstance(data["reading_gallons"], int) and data["reading_gallons"] >= 0
    assert data["reading_type"] in _enum_values(ReadingType)
    assert isinstance(data["usage_gallons"], int) and data["usage_gallons"] >= 0


def assert_master_meter_reading(data: dict):
    _assert_ledger(data)
    assert isinstance(data["cycle_id"], str)
    assert isinstance(data["master_gallons"], int) and data["master_gallons"] >= 0


def assert_rate_schedule(data: dict):
    _assert_common(data)
    assert isinstance(data["schedule_label"], str) and data["schedule_label"]
    assert isinstance(data["base_minimum_cents"], int) and data["base_minimum_cents"] >= 0
    assert isinstance(data["included_gallons"], int) and data["included_gallons"] >= 0
    assert isinstance(data["tier2_rate_cents_per_kgal"], int)
    assert isinstance(data["tier2_cap_gallons"], int)
    assert isinstance(data["tier3_rate_cents_per_kgal"], int)
    assert isinstance(data["tap_fee_schedule"], dict)
    assert isinstance(data["reconnect_fee_cents"], int) and data["reconnect_fee_cents"] >= 0
    assert data["status"] in _enum_values(RateScheduleStatus)


def assert_billing_cycle(data: dict):
    _assert_common(data)
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1
    assert is_iso8601_timestamp(data["period_start_utc"])
    assert is_iso8601_timestamp(data["period_end_utc"])
    assert is_iso8601_timestamp(data["due_date_utc"])
    assert data["status"] in _enum_values(CycleStatus)


def assert_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["member_id"], str)
    assert isinstance(data["tap_id"], str)
    assert isinstance(data["cycle_id"], str)
    assert isinstance(data["rate_schedule_id"], str)
    assert isinstance(data["usage_gallons"], int) and data["usage_gallons"] >= 0
    assert isinstance(data["usage_charge_cents"], int)
    assert isinstance(data["minimum_charge_cents"], int)
    assert isinstance(data["reconnect_fee_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert data["billing_status"] in _enum_values(BillingStatus)
    assert data["collection_status"] in _enum_values(CollectionStatus)
    # money conservation: paid amount never exceeds total
    assert 0 <= data["amount_paid_cents"] <= data["total_cents"]


def assert_payment(data: dict):
    _assert_common(data)
    assert isinstance(data["member_id"], str)
    assert isinstance(data["invoice_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["applied_cents"], int) and data["applied_cents"] >= 0
    assert data["status"] in _enum_values(PaymentStatus)


def assert_reserve_entry(data: dict):
    _assert_ledger(data)
    assert data["entry_type"] in _enum_values(ReserveEntryType)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["resulting_balance_cents"], int)


def assert_boil_order(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data["issued_utc"])
    assert isinstance(data["reason"], str) and data["reason"]
    assert is_iso8601_timestamp(data["notification_deadline_utc"])
    assert isinstance(data["notified_member_count"], int)
    assert data["notified_member_count"] >= 0
    assert data["status"] in _enum_values(BoilOrderStatus)


def assert_notification_receipt(data: dict):
    _assert_ledger(data)
    assert isinstance(data["boil_order_id"], str)
    assert isinstance(data["member_id"], str)
    assert data["channel"] in _enum_values(NotificationChannel)
    assert is_iso8601_timestamp(data["notified_utc"])


def assert_compliance_sample(data: dict):
    _assert_common(data)
    assert isinstance(data["boil_order_id"], str)
    assert isinstance(data["sample_point"], str) and data["sample_point"]
    assert is_iso8601_timestamp(data["collected_utc"])
    assert data["result"] in _enum_values(SampleResult)


def assert_board_resolution(data: dict):
    _assert_common(data)
    assert data["resolution_type"] in _enum_values(ResolutionType)
    assert isinstance(data["subject_id"], str)
    assert isinstance(data["payload"], dict)
    assert isinstance(data["votes_for"], int) and data["votes_for"] >= 0
    assert isinstance(data["votes_against"], int) and data["votes_against"] >= 0
    assert data["status"] in _enum_values(ResolutionStatus)


def assert_annexation_petition(data: dict):
    _assert_common(data)
    assert isinstance(data["petitioner_name"], str) and data["petitioner_name"]
    assert isinstance(data["parcel_acres"], int) and data["parcel_acres"] > 0
    assert isinstance(data["parent_service_area_id"], str)
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert data["status"] in _enum_values(PetitionStatus)


def assert_district_version_advanced(before: dict, after: dict, by: int = 1):
    """District-level events increment the district version by exactly 1."""
    assert after["version"] == before["version"] + by, (
        f"Expected district version {before['version']} + {by}, got {after['version']}"
    )
