"""Entity assertions and domain invariant checkers.

Field names are PRD-exact. Common-field checks (id / created_at / updated_at /
version) follow PRD §2.4: `id` is a server-minted UUID with no type prefix,
timestamps are ISO 8601, and `version` is an integer.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    MemberStatus,
    CommitmentLevel,
    SupplierStatus,
    SupplierProgramStatus,
    HoldbackPolicy,
    EnrollmentStatus,
    ExclusivityStatus,
    PurchaseReportStatus,
    VolumeAuditStatus,
    FindingSeverity,
    RebateAccrualStatus,
    DistributionStatus,
    ClawbackTriggerReason,
    ClawbackCaseStatus,
    HoldbackReleaseStatus,
)


def _assert_common_fields(data: dict, entity_name: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_name}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity_name}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity_name}.version must be an integer"


def assert_coop(data: dict):
    _assert_common_fields(data, "Coop")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["current_quarter_index"], int)
    assert data["current_quarter_index"] >= 0
    assert isinstance(data["pool_reserve_cents"], int)
    assert isinstance(data["retained_revenue_cents"], int)


def assert_member(data: dict):
    _assert_common_fields(data, "Member")
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["commitment_level"] in [e.value for e in CommitmentLevel]
    assert data["status"] in [e.value for e in MemberStatus]
    # PRD §3.2: activation stamps enrolled_quarter_index — a PENDING member
    # legitimately carries null (same nullability as churn_quarter_index).
    assert data.get("enrolled_quarter_index") is None or isinstance(
        data["enrolled_quarter_index"], int
    )
    assert data.get("churn_quarter_index") is None or isinstance(
        data["churn_quarter_index"], int
    )
    assert isinstance(data["lifetime_pass_through_cents"], int)
    assert isinstance(data["lifetime_clawback_cents"], int)
    assert isinstance(data["prior_audit_findings_count"], int)


def assert_supplier(data: dict):
    _assert_common_fields(data, "Supplier")
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data.get("onboarding_notes", ""), str)
    assert data["status"] in [e.value for e in SupplierStatus]


def assert_supplier_program(data: dict):
    _assert_common_fields(data, "SupplierProgram")
    assert isinstance(data["supplier_id"], str)
    assert isinstance(data["program_code"], str) and len(data["program_code"]) > 0
    assert isinstance(data["exclusivity_required"], bool)
    assert isinstance(data["exclusivity_threshold_pct"], int)
    assert isinstance(data["tier_schedule"], list)
    for tier in data["tier_schedule"]:
        assert isinstance(tier["min_qty"], int)
        assert isinstance(tier["rate_bps"], int)
    assert data["holdback_policy"] in [e.value for e in HoldbackPolicy]
    assert isinstance(data["negotiation_round"], int)
    assert data["status"] in [e.value for e in SupplierProgramStatus]


def assert_program_enrollment(data: dict):
    _assert_common_fields(data, "ProgramEnrollment")
    assert isinstance(data["member_id"], str)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["enrolled_quarter_index"], int)
    assert data.get("exit_quarter_index") is None or isinstance(
        data["exit_quarter_index"], int
    )
    assert data["status"] in [e.value for e in EnrollmentStatus]
    assert isinstance(data["exclusivity_share_pct"], int)
    assert data["exclusivity_status"] in [e.value for e in ExclusivityStatus]


def assert_purchase_report(data: dict):
    _assert_common_fields(data, "PurchaseReport")
    assert isinstance(data["enrollment_id"], str)
    assert isinstance(data["quarter_index"], int)
    assert isinstance(data["self_report_qty"], int)
    assert isinstance(data["self_report_cents"], int)
    assert data.get("audited_qty") is None or isinstance(data["audited_qty"], int)
    assert data.get("audited_cents") is None or isinstance(data["audited_cents"], int)
    assert data.get("revision_of_id") is None or isinstance(data["revision_of_id"], str)
    assert data["status"] in [e.value for e in PurchaseReportStatus]
    assert isinstance(data["submitted_at_quarter"], int)


def assert_volume_audit(data: dict):
    _assert_common_fields(data, "VolumeAudit")
    assert isinstance(data["enrollment_id"], str)
    assert isinstance(data["purchase_report_id"], str)
    assert isinstance(data["opened_quarter_index"], int)
    assert data.get("resolved_quarter_index") is None or isinstance(
        data["resolved_quarter_index"], int
    )
    assert data.get("finding_severity") is None or data["finding_severity"] in [
        e.value for e in FindingSeverity
    ]
    assert data.get("audited_qty") is None or isinstance(data["audited_qty"], int)
    assert data.get("audited_cents") is None or isinstance(data["audited_cents"], int)
    assert data["status"] in [e.value for e in VolumeAuditStatus]


def assert_rebate_accrual(data: dict):
    _assert_common_fields(data, "RebateAccrual")
    assert isinstance(data["enrollment_id"], str)
    assert isinstance(data["quarter_index"], int)
    assert isinstance(data["provisional_rebate_cents"], int)
    assert isinstance(data["final_rebate_cents"], int)
    assert isinstance(data["tier_applied_min_qty"], int)
    assert isinstance(data["pass_through_cents"], int)
    assert isinstance(data["retained_cents"], int)
    assert data["status"] in [e.value for e in RebateAccrualStatus]


def assert_quarterly_distribution(data: dict):
    _assert_common_fields(data, "QuarterlyDistribution")
    assert isinstance(data["coop_id"], str)
    assert isinstance(data["quarter_index"], int)
    for field in (
        "gross_rebate_cents",
        "total_pass_through_cents",
        "total_retained_cents",
        "holdback_cents",
        "clawback_offset_cents",
        "net_disbursed_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["status"] in [e.value for e in DistributionStatus]


def assert_clawback_case(data: dict):
    _assert_common_fields(data, "ClawbackCase")
    assert isinstance(data["member_id"], str)
    assert data["trigger_reason"] in [e.value for e in ClawbackTriggerReason]
    assert isinstance(data["trigger_quarter_index"], int)
    assert isinstance(data["gross_clawback_cents"], int)
    assert isinstance(data["net_clawback_cents"], int)
    assert isinstance(data["recovered_cents"], int)
    assert isinstance(data.get("dispute_note", ""), str)
    assert data["status"] in [e.value for e in ClawbackCaseStatus]


def assert_holdback_release(data: dict):
    _assert_common_fields(data, "HoldbackRelease")
    assert isinstance(data["member_id"], str)
    assert isinstance(data["source_distribution_id"], str)
    assert isinstance(data["release_quarter_index"], int)
    assert isinstance(data["release_cents"], int)
    assert data["status"] in [e.value for e in HoldbackReleaseStatus]


def assert_split_invariant(accrual: dict):
    """PRD §3.6: pass_through_cents + retained_cents == final_rebate_cents
    exactly — no cent drift is tolerated."""
    assert (
        accrual["pass_through_cents"] + accrual["retained_cents"]
        == accrual["final_rebate_cents"]
    ), (
        f"Split invariant violated: {accrual['pass_through_cents']} + "
        f"{accrual['retained_cents']} != {accrual['final_rebate_cents']}"
    )


def assert_pool_non_negative(coop: dict):
    """PRD §2.7: the pool balance must never go negative."""
    assert coop["pool_reserve_cents"] >= 0, (
        f"pool_reserve_cents went negative: {coop['pool_reserve_cents']}"
    )
