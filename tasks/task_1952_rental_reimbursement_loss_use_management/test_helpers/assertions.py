"""Entity assertions and domain invariant checkers (PRD §2.5, §2.6, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ClaimLossOfUseTrackStatus,
    ClaimOverallStatus,
    ClaimRentalTrackStatus,
    CommunicationChannel,
    CommunicationTemplate,
    CoverageVerificationStatus,
    ExtensionRequestStatus,
    InvoiceStatus,
    LossOfUseClaimStatus,
    MilestoneType,
    PartnerStatus,
    PayoutMethod,
    RecoveryCaseSource,
    RecoveryCaseStatus,
    RepairOrderStatus,
    ReservationStatus,
    VehicleClass,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def _assert_append_only_fields(data: dict):
    """Append-only records expose id + created_at only (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    assert "updated_at" not in data, "append-only records must not expose updated_at"
    assert "version" not in data, "append-only records must not expose version"


def assert_policyholder(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["policy_number"], str) and data["policy_number"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]


def assert_repair_shop(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["shop_name"], str) and data["shop_name"]
    assert isinstance(data["shop_code"], str) and data["shop_code"]


def assert_rental_partner(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["partner_name"], str) and data["partner_name"]
    assert isinstance(data["partner_code"], str) and data["partner_code"]
    for cls in ("economy", "standard", "premium"):
        assert isinstance(data[f"{cls}_rate_cents"], int) and data[f"{cls}_rate_cents"] > 0
        assert isinstance(data[f"{cls}_capacity"], int) and data[f"{cls}_capacity"] >= 0
    assert data["status"] in [s.value for s in PartnerStatus]


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["policyholder_id"])
    assert isinstance(data["incident_date"], str) and data["incident_date"]
    assert isinstance(data["coverage_daily_limit_cents"], int)
    assert isinstance(data["coverage_duration_cap_days"], int)
    assert isinstance(data["loss_of_use_per_diem_cents"], int)
    assert isinstance(data["rental_reserve_cents"], int)
    assert isinstance(data["authorized_days_total"], int)
    assert isinstance(data["recovery_balance_cents"], int)
    assert data["rental_track_status"] in [s.value for s in ClaimRentalTrackStatus]
    assert data["loss_of_use_track_status"] in [s.value for s in ClaimLossOfUseTrackStatus]
    assert data["overall_status"] in [s.value for s in ClaimOverallStatus]


def assert_coverage_verification(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["claim_id"])
    assert data["status"] in [s.value for s in CoverageVerificationStatus]


def assert_repair_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["claim_id"])
    assert is_valid_uuid(data["shop_id"])
    assert isinstance(data["estimated_completion_date"], str)
    assert data["actual_completion_date"] is None or \
        isinstance(data["actual_completion_date"], str)
    assert isinstance(data["labor_hours_estimate"], int) and data["labor_hours_estimate"] > 0
    assert data["status"] in [s.value for s in RepairOrderStatus]


def assert_repair_milestone(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["repair_order_id"])
    assert data["milestone_type"] in [s.value for s in MilestoneType]
    assert is_iso8601_timestamp(data["reported_at"]), \
        "reported_at must be an ISO 8601 timestamp"


def assert_rental_reservation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["claim_id"])
    assert is_valid_uuid(data["rental_partner_id"])
    assert is_valid_uuid(data["repair_order_id"])
    assert data["vehicle_class"] in [s.value for s in VehicleClass]
    assert isinstance(data["pickup_date"], str)
    assert isinstance(data["authorized_return_date"], str)
    assert data["actual_pickup_date"] is None or isinstance(data["actual_pickup_date"], str)
    assert data["actual_return_date"] is None or isinstance(data["actual_return_date"], str)
    assert isinstance(data["daily_rate_cents"], int)
    assert isinstance(data["authorized_days"], int)
    assert data["consumed_days"] is None or isinstance(data["consumed_days"], int)
    assert isinstance(data["unnecessary_days"], int)
    assert isinstance(data["estimated_charge_cents"], int)
    assert isinstance(data["audited_charge_cents"], int)
    assert data["status"] in [s.value for s in ReservationStatus]


def assert_extension_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["reservation_id"])
    assert is_valid_uuid(data["milestone_id"])
    assert isinstance(data["requested_additional_days"], int) \
        and data["requested_additional_days"] >= 1
    assert data["granted_days"] is None or isinstance(data["granted_days"], int)
    assert data["status"] in [s.value for s in ExtensionRequestStatus]


def assert_class_change_record(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["reservation_id"])
    assert data["from_class"] in [s.value for s in VehicleClass]
    assert data["to_class"] in [s.value for s in VehicleClass]
    assert isinstance(data["effective_date"], str)
    assert isinstance(data["upgrade_waiver"], bool)
    assert isinstance(data["per_day_customer_cents"], int)
    assert isinstance(data["customer_responsibility_cents"], int)
    assert isinstance(data["insurer_delta_cents"], int)


def assert_loss_of_use_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["claim_id"])
    assert isinstance(data["vehicle_description"], str) and data["vehicle_description"]
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["claimed_amount_cents"], int) and data["claimed_amount_cents"] > 0
    assert data["payout_method"] in [s.value for s in PayoutMethod]
    assert isinstance(data["documentation_provided"], bool)
    assert data["payout_cents"] is None or isinstance(data["payout_cents"], int)
    assert data["status"] in [s.value for s in LossOfUseClaimStatus]


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["reservation_id"])
    assert is_valid_uuid(data["rental_partner_id"])
    assert isinstance(data["invoice_number"], str) and data["invoice_number"]
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["daily_rate_cents"], int) and data["daily_rate_cents"] > 0
    assert isinstance(data["tax_cents"], int) and data["tax_cents"] >= 0
    assert isinstance(data["fees_cents"], int) and data["fees_cents"] >= 0
    assert isinstance(data["total_cents"], int)
    assert data["audited_payable_cents"] is None or \
        isinstance(data["audited_payable_cents"], int)
    assert isinstance(data["unauthorized_days"], int)
    assert data["status"] in [s.value for s in InvoiceStatus]


def assert_recovery_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["claim_id"])
    assert is_valid_uuid(data["reservation_id"])
    assert data["source"] in [s.value for s in RecoveryCaseSource]
    assert isinstance(data["unnecessary_days"], int)
    assert isinstance(data["assessed_amount_cents"], int)
    assert isinstance(data["recovered_amount_cents"], int)
    assert isinstance(data["waived_amount_cents"], int)
    assert isinstance(data["outstanding_amount_cents"], int)
    assert data["status"] in [s.value for s in RecoveryCaseStatus]


def assert_communication_log(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["claim_id"])
    assert data["channel"] in [s.value for s in CommunicationChannel]
    assert data["template"] in [s.value for s in CommunicationTemplate]
    assert isinstance(data["body_summary"], str)
    assert is_iso8601_timestamp(data["sent_at"]), "sent_at must be an ISO 8601 timestamp"


# ------------------------------------------------------- domain invariants


def assert_recovery_case_conservation(case: dict):
    """PRD §2.6: assessed always equals recovered + waived + outstanding."""
    assert case["assessed_amount_cents"] == (
        case["recovered_amount_cents"]
        + case["waived_amount_cents"]
        + case["outstanding_amount_cents"]
    ), (
        f"Recovery conservation violated: assessed {case['assessed_amount_cents']} != "
        f"recovered {case['recovered_amount_cents']} + waived "
        f"{case['waived_amount_cents']} + outstanding {case['outstanding_amount_cents']}"
    )


def assert_timestamp_matches_clock(stamped: str, expected_instant: str):
    """Compare a clock-stamped field to the logical-clock instant it must carry.

    The stamped instant is PRD-pinned; its string formatting is not, so both
    sides are parsed before comparison.
    """
    def _parse(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    assert _parse(stamped) == _parse(expected_instant), (
        f"Expected clock stamp {expected_instant}, got {stamped}"
    )
