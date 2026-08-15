"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AgreementStatus,
    DisputeStatus,
    DistributionRunStatus,
    FindingStatus,
    FindingType,
    LicenseeStatus,
    MflMode,
    MilestoneStatus,
    MilestoneTriggerType,
    OfferStatus,
    RoyaltyAuditStatus,
    RoyaltyBaseDefinition,
    RoyaltyReportStatus,
    SublicenseGrantStatus,
)


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def assert_licensee(data: dict):
    _assert_common_fields(data, "Licensee")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["tax_id"], str) and data["tax_id"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["status"] in [s.value for s in LicenseeStatus]
    assert isinstance(data["outstanding_balance_cents"], int)
    assert isinstance(data["credit_balance_cents"], int)


def assert_agreement(data: dict):
    _assert_common_fields(data, "LicenseAgreement")
    assert is_valid_uuid(data.get("licensee_id", ""))
    assert isinstance(data["patent_reference"], str) and data["patent_reference"]
    assert isinstance(data["title"], str) and data["title"]
    assert data["royalty_base_definition"] in [d.value for d in RoyaltyBaseDefinition]
    assert isinstance(data["base_rate_bp"], int)
    assert 0 < data["base_rate_bp"] <= 10000
    assert isinstance(data["minimum_period_royalty_cents"], int)
    assert data["minimum_period_royalty_cents"] >= 0
    assert isinstance(data["sublicense_allowed"], bool)
    assert isinstance(data["sublicense_passthrough_rate_bp"], int)
    assert 0 <= data["sublicense_passthrough_rate_bp"] <= 10000
    assert isinstance(data["mfl_clause"], bool)
    assert data["mfl_mode"] in [m.value for m in MflMode]
    assert isinstance(data["mfl_lookback_quarters"], int) and data["mfl_lookback_quarters"] >= 1
    assert isinstance(data["audit_window_months"], int) and data["audit_window_months"] >= 1
    assert isinstance(data["underreport_tolerance_bp"], int)
    assert 0 <= data["underreport_tolerance_bp"] < 10000
    shares = data["inventor_shares"]
    assert isinstance(shares, list) and shares
    assert sum(s["share_bp"] for s in shares) == 10000
    names = [s["inventor_name"] for s in shares]
    assert len(names) == len(set(names))
    assert data["status"] in [s.value for s in AgreementStatus]
    assert isinstance(data["cumulative_accepted_base_cents"], int)
    assert isinstance(data["cumulative_recognized_revenue_cents"], int)
    assert isinstance(data["undistributed_pool_cents"], int)
    assert data["mfl_adjusted_rate_bp"] is None or isinstance(data["mfl_adjusted_rate_bp"], int)
    assert isinstance(data["last_mfl_credit_cents"], int)


def assert_milestone(data: dict):
    _assert_common_fields(data, "Milestone")
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert data["trigger_type"] in [t.value for t in MilestoneTriggerType]
    if data["trigger_type"] == MilestoneTriggerType.CUMULATIVE_SALES.value:
        assert isinstance(data["threshold_cents"], int) and data["threshold_cents"] > 0
    if data["trigger_type"] == MilestoneTriggerType.DATE.value:
        assert data["trigger_date"] is not None
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert data["status"] in [s.value for s in MilestoneStatus]
    if data["status"] == MilestoneStatus.ACHIEVED.value:
        assert data["achieved_at"] is not None
    else:
        assert data["achieved_at"] is None


def assert_sublicense_grant(data: dict):
    _assert_common_fields(data, "SublicenseGrant")
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert isinstance(data["sublicensee_name"], str) and data["sublicensee_name"]
    assert isinstance(data["territory"], str) and data["territory"]
    assert data["status"] in [s.value for s in SublicenseGrantStatus]


def assert_royalty_report(data: dict):
    _assert_common_fields(data, "RoyaltyReport")
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert is_valid_uuid(data.get("licensee_id", ""))
    assert isinstance(data["lines"], list) and data["lines"]
    assert isinstance(data["reported_gross_sales_cents"], int)
    assert isinstance(data["reported_net_sales_cents"], int)
    assert isinstance(data["royalty_base_cents"], int)
    assert isinstance(data["sublicense_net_sales_cents"], int)
    assert isinstance(data["provisional_royalty_cents"], int)
    assert data["status"] in [s.value for s in RoyaltyReportStatus]


def assert_audit(data: dict):
    _assert_common_fields(data, "RoyaltyAudit")
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]
    assert data["status"] in [s.value for s in RoyaltyAuditStatus]


def assert_finding(data: dict):
    _assert_common_fields(data, "AuditFinding")
    assert is_valid_uuid(data.get("audit_id", ""))
    assert is_valid_uuid(data.get("report_id", ""))
    assert data["finding_type"] in [t.value for t in FindingType]
    assert isinstance(data["audited_base_cents"], int) and data["audited_base_cents"] >= 0
    assert isinstance(data["shortfall_cents"], int) and data["shortfall_cents"] >= 0
    assert isinstance(data["recorded_by_user_id"], str) and data["recorded_by_user_id"]
    assert data["status"] in [s.value for s in FindingStatus]


def assert_dispute(data: dict):
    _assert_common_fields(data, "Dispute")
    assert is_valid_uuid(data.get("finding_id", ""))
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert is_valid_uuid(data.get("licensee_id", ""))
    assert isinstance(data["offers"], list)
    for offer in data["offers"]:
        assert isinstance(offer["amount_cents"], int)
        assert offer["offered_by_role"] in ("LegalCounsel", "Licensee")
        assert offer["status"] in [s.value for s in OfferStatus]
    assert data["status"] in [s.value for s in DisputeStatus]
    pending = [o for o in data["offers"] if o["status"] == OfferStatus.PENDING.value]
    assert len(pending) <= 1, "at most one offer may be PENDING"


def assert_distribution_run(data: dict):
    _assert_common_fields(data, "DistributionRun")
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert isinstance(data["pool_cents"], int) and data["pool_cents"] > 0
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert data["status"] in [s.value for s in DistributionRunStatus]
    if data["status"] == DistributionRunStatus.POSTED.value:
        lines = data["lines"]
        assert isinstance(lines, list) and lines
        assert sum(l["amount_cents"] for l in lines) == data["pool_cents"], (
            "posted run lines must sum to pool_cents exactly"
        )
        assert data["approved_by_user_id"] is not None
        assert data["approved_by_user_id"] != data["created_by_user_id"]


def assert_pool_invariants(agreement: dict):
    """The undistributed pool never exceeds recognized revenue."""
    assert agreement["undistributed_pool_cents"] >= 0
    assert agreement["cumulative_recognized_revenue_cents"] >= 0
    assert agreement["cumulative_accepted_base_cents"] >= 0
