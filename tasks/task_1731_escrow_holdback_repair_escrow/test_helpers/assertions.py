"""Entity assertions and domain invariant checkers (PRD §2.5, §2.7, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ApprovalStatus,
    ApproverRole,
    BidStatus,
    DisputeStatus,
    DrawStatus,
    EscrowFileStatus,
    ExtensionReason,
    ExtensionStatus,
    HoldbackStatus,
    InspectionPurpose,
    InspectionStatus,
    LedgerEntryType,
    PledgeStatus,
    WorkOrderStatus,
)


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        # PRD §2.5: every resource except the trust ledger entry carries
        # updated_at and an integer version.
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), "version must be an integer"
    else:
        # PRD §2.5: a ledger entry carries only id and created_at from the
        # common set; updated_at and version are absent.
        assert "updated_at" not in data, "ledger entries must not carry updated_at"
        assert "version" not in data, "ledger entries must not carry version"


def assert_escrow_file(data: dict):
    _assert_common(data)
    assert isinstance(data["property_address"], str) and data["property_address"]
    assert isinstance(data["closing_date"], str) and data["closing_date"]
    assert isinstance(data["buyer_user_id"], str) and data["buyer_user_id"]
    assert isinstance(data["seller_user_id"], str) and data["seller_user_id"]
    assert isinstance(data["lender_user_id"], str) and data["lender_user_id"]
    assert data["status"] in [s.value for s in EscrowFileStatus]


def assert_holdback(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("escrow_file_id", "")), "escrow_file_id must be a UUID"
    assert isinstance(data["repair_estimate_cents"], int) and data["repair_estimate_cents"] > 0
    assert isinstance(data["contingency_pct"], int) and 10 <= data["contingency_pct"] <= 25
    assert isinstance(data["holdback_amount_cents"], int) and data["holdback_amount_cents"] > 0
    assert data["commitment_basis_cents"] is None or isinstance(data["commitment_basis_cents"], int)
    assert data["funding_source"] in ("SELLER_PROCEEDS", "BUYER_DEPOSIT", "SPLIT_EQUAL")
    assert data["overrun_responsibility"] in ("BUYER", "SELLER", "SPLIT_EQUAL")
    assert data["expiration_terms"] in ("RETURN_TO_SELLER", "RELEASE_TO_BUYER", "SPLIT_EQUAL")
    assert isinstance(data["work_deadline_date"], str)
    assert isinstance(data["hard_stop_date"], str)
    assert isinstance(data["exterior_work_flag"], bool)
    assert isinstance(data["granted_extension_days"], int) and data["granted_extension_days"] >= 0
    assert isinstance(data["effective_deadline_date"], str)
    assert data["lender_approval_required"] is True
    assert isinstance(data["insurer_approval_required"], bool)
    assert data["selected_bid_id"] is None or isinstance(data["selected_bid_id"], str)
    assert data["status"] in [s.value for s in HoldbackStatus]
    assert isinstance(data["trust_balance_cents"], int)
    assert isinstance(data["reserved_cents"], int) and data["reserved_cents"] >= 0
    assert isinstance(data["total_disbursed_cents"], int) and data["total_disbursed_cents"] >= 0
    assert isinstance(data["total_shortfall_deposited_cents"], int)
    assert isinstance(data["work_verified"], bool)
    assert isinstance(data["disbursement_frozen"], bool)
    assert data["closeout_status"] in ("NOT_READY", "READY_TO_CLOSE")
    assert data["disposition_override"] in (
        None, "RETURN_TO_SELLER", "RELEASE_TO_BUYER", "SPLIT_EQUAL",
    )


def assert_approval(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("holdback_id", "")), "holdback_id must be a UUID"
    assert data["approver_role"] in [r.value for r in ApproverRole]
    assert data["status"] in [s.value for s in ApprovalStatus]
    assert data["approver_user_id"] is None or isinstance(data["approver_user_id"], str)
    assert data["holdback_version_at_decision"] is None or isinstance(
        data["holdback_version_at_decision"], int
    )
    assert data["decided_at"] is None or is_iso8601_timestamp(data["decided_at"])


def assert_bid(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("holdback_id", "")), "holdback_id must be a UUID"
    assert isinstance(data["contractor_user_id"], str) and data["contractor_user_id"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["scope_text"], str)
    assert data["status"] in [s.value for s in BidStatus]


def assert_work_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("holdback_id", "")), "holdback_id must be a UUID"
    assert isinstance(data["contractor_user_id"], str) and data["contractor_user_id"]
    assert isinstance(data["agreed_amount_cents"], int) and data["agreed_amount_cents"] > 0
    assert is_iso8601_timestamp(data["started_at"])
    assert isinstance(data["completion_deadline_date"], str)
    assert data["status"] in [s.value for s in WorkOrderStatus]
    assert isinstance(data["failed_final_count"], int) and data["failed_final_count"] >= 0
    assert data["submitted_completion_at"] is None or is_iso8601_timestamp(
        data["submitted_completion_at"]
    )


def assert_inspection(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("holdback_id", "")), "holdback_id must be a UUID"
    assert isinstance(data["inspector_user_id"], str) and data["inspector_user_id"]
    assert data["purpose"] in [p.value for p in InspectionPurpose]
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["status"] in [s.value for s in InspectionStatus]
    assert data["reported_at"] is None or is_iso8601_timestamp(data["reported_at"])


def assert_draw_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("holdback_id", "")), "holdback_id must be a UUID"
    assert isinstance(data["contractor_user_id"], str) and data["contractor_user_id"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["description"], str)
    assert isinstance(data["is_final"], bool)
    assert data["status"] in [s.value for s in DrawStatus]
    assert data["approved_at"] is None or is_iso8601_timestamp(data["approved_at"])
    assert data["paid_at"] is None or is_iso8601_timestamp(data["paid_at"])


def assert_extension_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("holdback_id", "")), "holdback_id must be a UUID"
    assert isinstance(data["requester_user_id"], str) and data["requester_user_id"]
    assert data["reason"] in [r.value for r in ExtensionReason]
    assert isinstance(data["requested_days"], int) and 1 <= data["requested_days"] <= 45
    assert data["status"] in [s.value for s in ExtensionStatus]
    assert data["granted_days"] is None or isinstance(data["granted_days"], int)
    assert data["decided_at"] is None or is_iso8601_timestamp(data["decided_at"])


def assert_dispute(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("holdback_id", "")), "holdback_id must be a UUID"
    assert data["initiator_role"] in ("BUYER", "SELLER")
    assert isinstance(data["initiator_user_id"], str) and data["initiator_user_id"]
    assert data["category"] in (
        "WORK_QUALITY", "DRAW_DENIAL", "DEADLINE", "EXPENSE_RESPONSIBILITY", "OTHER",
    )
    assert isinstance(data["claimed_amount_cents"], int) and data["claimed_amount_cents"] >= 0
    assert isinstance(data["statement"], str)
    assert data["status"] in [s.value for s in DisputeStatus]
    assert data["resolved_at"] is None or is_iso8601_timestamp(data["resolved_at"])


def assert_shortfall_pledge(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("holdback_id", "")), "holdback_id must be a UUID"
    assert data["payer_role"] in ("BUYER", "SELLER")
    assert isinstance(data["payer_user_id"], str) and data["payer_user_id"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in [s.value for s in PledgeStatus]
    assert data["deposited_at"] is None or is_iso8601_timestamp(data["deposited_at"])


def assert_ledger_entry(data: dict):
    _assert_common(data, with_version=False)
    assert is_valid_uuid(data.get("holdback_id", "")), "holdback_id must be a UUID"
    assert isinstance(data["seq"], int) and data["seq"] >= 1
    assert data["entry_type"] in [t.value for t in LedgerEntryType]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["running_balance_cents"], int)
    assert isinstance(data.get("memo", ""), str)


def assert_ledger_invariants(entries: list, expected_trust_balance: int):
    """PRD §2.7: trust_balance equals the signed sum of amounts and equals the
    last entry's running balance; running balances accumulate chronologically."""
    running = 0
    for i, entry in enumerate(entries):
        assert entry["seq"] == i + 1, "seq must be a per-holdback monotonic sequence starting at 1"
        running += entry["amount_cents"]
        assert entry["running_balance_cents"] == running, (
            f"running balance of entry seq {entry['seq']} must equal the chronological sum"
        )
    signed_sum = sum(e["amount_cents"] for e in entries)
    assert signed_sum == expected_trust_balance, (
        f"sum of signed amounts {signed_sum} must equal trust_balance_cents "
        f"{expected_trust_balance}"
    )
    if entries:
        assert entries[-1]["running_balance_cents"] == expected_trust_balance
