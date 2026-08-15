"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §2.8, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    JobStatus, StructureStatus, BillingStatus, PolicyCoverageType,
    RoomType, RoomStatus, ItemCategory, ConditionTriage, ProcessingStatus,
    DisposalMethod, DisposalRecordStatus, ProcessCode, CleaningTaskStatus,
    ClimateClass, VaultPosture, PlacementStatus, ReleaseReason, SpecialtyType,
    ReferralStatus, CustodyEventType, ClaimType, ClaimStatus, ScheduleStatus,
    StatementStatus, InvoiceStatus,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_pack_out_job(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["claim_number"], str) and data["claim_number"]
    assert isinstance(data["property_address"], str)
    assert isinstance(data["carrier_name"], str)
    assert data["policy_coverage_type"] in [e.value for e in PolicyCoverageType]
    assert data["status"] in [e.value for e in JobStatus]
    assert data["structure_status"] in [e.value for e in StructureStatus]
    assert data["billing_status"] in [e.value for e in BillingStatus]
    assert isinstance(data["accrued_storage_total_cents"], int)


def assert_room(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["room_type"] in [e.value for e in RoomType]
    assert data["status"] in [e.value for e in RoomStatus]
    assert isinstance(data["item_count"], int) and data["item_count"] >= 0


def assert_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["barcode"], str) and data["barcode"]
    assert data["item_category"] in [e.value for e in ItemCategory]
    assert isinstance(data["declared_value_cents"], int) and data["declared_value_cents"] >= 0
    assert isinstance(data["volume_cu_ft"], int) and data["volume_cu_ft"] >= 1
    assert isinstance(data["hazmat_flag"], bool)
    assert isinstance(data["smoke_damage_flag"], bool)
    assert data["condition_triage"] in [e.value for e in ConditionTriage]
    assert data["processing_status"] in [e.value for e in ProcessingStatus]
    assert isinstance(data["is_high_value"], bool)
    assert isinstance(data["triage_count"], int) and data["triage_count"] >= 0


def assert_disposal_record(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [e.value for e in DisposalRecordStatus]
    if data.get("disposal_method") is not None:
        assert data["disposal_method"] in [e.value for e in DisposalMethod]


def assert_cleaning_task(data: dict):
    _assert_common_fields(data)
    assert data["process_code"] in [e.value for e in ProcessCode]
    assert isinstance(data["deodorization_required"], bool)
    assert data["status"] in [e.value for e in CleaningTaskStatus]
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0
    if data["status"] == "PASSED":
        assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0


def assert_vault(data: dict):
    _assert_common_fields(data)
    assert data["climate_class"] in [e.value for e in ClimateClass]
    assert isinstance(data["capacity_cu_ft"], int) and data["capacity_cu_ft"] > 0
    assert isinstance(data["monthly_rate_cents_per_cu_ft"], int)
    assert isinstance(data["occupied_cu_ft"], int)
    assert data["posture"] in [e.value for e in VaultPosture]


def assert_vault_invariants(data: dict):
    """PRD §2.8: posture is FULL exactly when occupancy equals capacity."""
    assert_vault(data)
    assert 0 <= data["occupied_cu_ft"] <= data["capacity_cu_ft"]
    expected_posture = "FULL" if data["occupied_cu_ft"] == data["capacity_cu_ft"] else "OPEN"
    assert data["posture"] == expected_posture, (
        f"posture {data['posture']} inconsistent with occupied "
        f"{data['occupied_cu_ft']} / capacity {data['capacity_cu_ft']}"
    )


def assert_storage_placement(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [e.value for e in PlacementStatus]
    assert isinstance(data["monthly_rate_cents"], int) and data["monthly_rate_cents"] > 0
    if data["status"] == "RELEASED":
        assert data["release_reason"] in [e.value for e in ReleaseReason]
        assert isinstance(data["released_on"], str) and data["released_on"]


def assert_subcontractor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    for s in data["specialty_types"]:
        assert s in [e.value for e in SpecialtyType]
    assert isinstance(data["max_concurrent_referrals"], int) and data["max_concurrent_referrals"] >= 1
    assert isinstance(data["active_referral_count"], int) and data["active_referral_count"] >= 0


def assert_specialty_referral(data: dict):
    _assert_common_fields(data)
    assert data["specialty_type"] in [e.value for e in SpecialtyType]
    assert isinstance(data["quoted_cost_cents"], int) and data["quoted_cost_cents"] >= 0
    assert isinstance(data["markup_pct"], int)
    assert data["status"] in [e.value for e in ReferralStatus]
    if data["status"] == "QA_ACCEPTED":
        assert isinstance(data["billed_cost_cents"], int) and data["billed_cost_cents"] >= 0


def assert_custody_event(data: dict):
    """Append-only event: id + created_at only; no updated_at, no version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, "custody events never carry updated_at"
    assert "version" not in data, "custody events never carry version"
    assert data["event_type"] in [e.value for e in CustodyEventType]
    assert isinstance(data["event_at"], str) and data["event_at"]
    assert isinstance(data["actor_name"], str) and data["actor_name"]
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert isinstance(data["referral_id"], str) and data["referral_id"]


def assert_handling_claim(data: dict):
    _assert_common_fields(data)
    assert data["claim_type"] in [e.value for e in ClaimType]
    assert isinstance(data["replacement_cost_cents"], int) and data["replacement_cost_cents"] >= 0
    assert isinstance(data["item_age_years"], int) and data["item_age_years"] >= 0
    assert data["status"] in [e.value for e in ClaimStatus]
    assert isinstance(data["filed_by_user_id"], str) and data["filed_by_user_id"]
    if data["status"] in ("APPROVED", "SETTLED"):
        assert data["settlement_variant"] in ("ACV", "RCV")
        assert isinstance(data["settlement_amount_cents"], int)


def assert_pack_back_schedule(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["crew_id"], str) and data["crew_id"]
    assert isinstance(data["window_start_hour"], int)
    assert isinstance(data["window_end_hour"], int)
    assert data["window_end_hour"] > data["window_start_hour"]
    assert data["status"] in [e.value for e in ScheduleStatus]
    assert isinstance(data["reschedule_count"], int) and data["reschedule_count"] >= 0


def assert_storage_statement(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [e.value for e in StatementStatus]
    assert data["period_end"] > data["period_start"]
    assert isinstance(data["provisional_total_cents"], int)
    if data["status"] == "PROVISIONAL":
        assert data.get("final_total_cents") is None
    if data["status"] in ("FINALIZED", "INVOICED"):
        assert isinstance(data["final_total_cents"], int)


def assert_carrier_invoice(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [e.value for e in InvoiceStatus]
    for field in ("storage_cents", "admin_fee_cents", "total_cents",
                  "claim_credit_cents", "amount_paid_cents", "balance_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_invoice_invariants(data: dict):
    """PRD §3.8: balance is always total minus claim credit minus amount paid."""
    assert_carrier_invoice(data)
    assert data["total_cents"] == (
        data["storage_cents"] + data["adjustment_cents"] + data["admin_fee_cents"]
    ), "total_cents must equal storage + adjustment + admin fee"
    assert data["balance_cents"] == (
        data["total_cents"] - data["claim_credit_cents"] - data["amount_paid_cents"]
    ), "balance_cents must equal total - claim_credit - amount_paid"
