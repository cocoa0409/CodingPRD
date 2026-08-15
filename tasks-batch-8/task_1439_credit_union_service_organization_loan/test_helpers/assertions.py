"""Entity assertions and domain invariant checkers (PRD §2.6, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Every resource carries id / created_at / updated_at / version (PRD §2.6)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_credit_union(data: dict):
    _assert_common(data)
    assert isinstance(data["charter_number"], str) and data["charter_number"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["cu_type"] in ("ORIGINATOR", "BUYER", "DUAL")
    assert isinstance(data["total_assets_cents"], int)
    assert isinstance(data["net_worth_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["net_worth_ratio"], (int, float))
    assert isinstance(data["total_committed_principal_cents"], int)


def assert_cuso(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["service_line"] in ("LENDING", "PAYMENTS", "COMPLIANCE", "TECHNOLOGY")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["total_approved_investment_cents"], int)
    assert isinstance(data["open_critical_finding_count"], int)


def assert_investment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("credit_union_id", ""))
    assert is_valid_uuid(data.get("cuso_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["approval_basis"] in ("STANDARD", "ENHANCED")
    assert data["status"] in ("PENDING_REVIEW", "APPROVED", "REJECTED", "RESCINDED")


def assert_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("cuso_id", ""))
    assert is_valid_uuid(data.get("originator_id", ""))
    assert isinstance(data["servicing_fee_bps"], int)
    assert 1 <= data["remittance_due_day"] <= 28
    assert data["day_count_convention"] in ("THIRTY_360", "ACT_360")
    assert isinstance(data["late_remittance_count"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "DELINQUENT", "SUSPENDED", "TERMINATED")


def assert_offering(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("servicing_agreement_id", ""))
    assert isinstance(data["pool_principal_cents"], int) and data["pool_principal_cents"] > 0
    assert isinstance(data["min_share_pct"], (int, float))
    assert isinstance(data["yield_rate_bps"], int)
    assert data["loss_basis"] in ("OUTSTANDING", "COMMITTED")
    assert data["status"] in ("DRAFT", "OPEN", "SUSPENDED", "CLOSED", "EXPIRED", "WITHDRAWN")
    assert isinstance(data["committed_principal_cents"], int)
    assert isinstance(data["remaining_principal_cents"], int)


def assert_certificate(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("offering_id", ""))
    assert is_valid_uuid(data.get("buyer_id", ""))
    assert isinstance(data["committed_amount_cents"], int) and data["committed_amount_cents"] > 0
    assert data["status"] in ("PENDING_DILIGENCE", "COMMITTED", "ACTIVE", "EXCEPTION",
                              "PAID_OFF", "DECLINED", "RESCINDED", "REPURCHASED")
    assert isinstance(data["funded_amount_cents"], int)
    assert isinstance(data["outstanding_principal_cents"], int)
    assert isinstance(data["cumulative_interest_cents"], int)
    assert isinstance(data["cumulative_loss_cents"], int)


def assert_exception(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("certificate_id", ""))
    assert data["exception_type"] in ("MISSING_NOTE", "STALE_APPRAISAL",
                                      "INSURANCE_LAPSE", "UCC_FILING_GAP")
    assert data["status"] in ("OPEN", "CURE_SUBMITTED", "REJECTED", "CURED", "ESCALATED")
    assert isinstance(data["cure_attempt_count"], int)


def assert_remittance(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("certificate_id", ""))
    assert isinstance(data["collections_cents"], int)
    assert isinstance(data["interest_portion_cents"], int)
    assert isinstance(data["servicing_fee_cents"], int)
    assert isinstance(data["principal_portion_cents"], int)
    assert isinstance(data["penalty_cents"], int)
    assert data["status"] in ("SCHEDULED", "PAID", "PAID_LATE", "LATE_UNPAID", "REVERSED")


def assert_surveillance_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("servicing_agreement_id", ""))
    assert data["weighting_basis"] in ("OUTSTANDING", "COMMITTED")
    assert data["status"] in ("CURRENT", "SUPERSEDED")
    assert isinstance(data["total_outstanding_principal_cents"], int)
    assert isinstance(data["active_certificate_count"], int)
    assert isinstance(data["weighted_avg_yield_bps"], int)
    assert isinstance(data["delinquent_remittance_count"], int)


def assert_exam(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("cuso_id", ""))
    assert data["status"] in ("IN_PROGRESS", "FINALIZED")


def assert_finding(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("exam_id", ""))
    assert data["severity"] in ("LOW", "MODERATE", "HIGH", "CRITICAL")
    assert data["status"] in ("OPEN", "VERIFYING", "REOPENED", "CLOSED")
    assert isinstance(data["recorded_by_user_id"], str) and data["recorded_by_user_id"]


def assert_loss_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("offering_id", ""))
    assert isinstance(data["loss_amount_cents"], int) and data["loss_amount_cents"] > 0
    assert data["status"] in ("REPORTED", "ALLOCATED")


def assert_repurchase_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("certificate_id", ""))
    assert data["trigger_reason"] in ("DOCUMENTATION_DEFAULT", "MATERIAL_BREACH", "FRAUD")
    assert data["status"] in ("TRIGGERED", "DISPUTED", "COMPLETED", "WITHDRAWN")


def assert_offering_aggregates_consistent(offering: dict):
    """remaining_principal_cents == pool_principal_cents - committed_principal_cents."""
    assert offering["remaining_principal_cents"] == (
        offering["pool_principal_cents"] - offering["committed_principal_cents"]
    ), (f"remaining {offering['remaining_principal_cents']} != pool "
        f"{offering['pool_principal_cents']} - committed {offering['committed_principal_cents']}")
