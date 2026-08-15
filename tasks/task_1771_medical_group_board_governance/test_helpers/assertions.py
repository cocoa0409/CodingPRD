"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_governance_policy(data: dict):
    _assert_common_fields(data)
    assert data["singleton_key"] == "GLOBAL"
    assert isinstance(data["total_shares_authorized"], int)
    assert isinstance(data["board_quorum_count"], int)
    assert isinstance(data["treasury_shares"], int)
    assert isinstance(data["comp_policy_version"], int)


def assert_physician(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["partnership_status"] in (
        "ASSOCIATE", "PARTNER_TRACK", "SHAREHOLDER", "EXITING", "EXITED"
    )
    assert data["standing"] in ("GOOD_STANDING", "PROBATION", "SUSPENDED")
    assert isinstance(data["shares_held"], int)
    assert isinstance(data["capital_account_balance_cents"], int)


def assert_board_seat(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["seat_label"], str) and data["seat_label"]
    assert data["seat_class"] in ("CLINICAL", "AT_LARGE", "EX_OFFICIO")
    assert data["status"] in ("VACANT", "FILLED")


def assert_committee(data: dict):
    _assert_common_fields(data)
    assert data["committee_type"] in ("QUALITY", "FINANCE", "COMPENSATION")
    assert data["approval_threshold"] in ("SIMPLE_MAJORITY", "SUPERMAJORITY")
    assert data["status"] in ("CHARTERED", "ACTIVE", "IMPAIRED", "DISSOLVED")
    assert isinstance(data["members"], list)
    assert data["active_member_count"] == len(data["members"])


def assert_buy_in_offer(data: dict):
    _assert_common_fields(data)
    assert data["target_tier"] in ("PARTNER_TRACK", "SHAREHOLDER")
    assert data["status"] in ("OFFERED", "ACCEPTED", "COMPLETED", "DECLINED", "EXPIRED")
    assert isinstance(data["final_amount_cents"], int)
    assert isinstance(data["installment_schedule_cents"], list)
    assert len(data["installment_schedule_cents"]) == data["installment_count"]


def assert_motion(data: dict):
    _assert_common_fields(data)
    assert data["motion_type"] in (
        "CHARTER_AMENDMENT", "COMP_POLICY", "CAPITAL_CALL",
        "DISTRIBUTION", "BUYOUT_APPROVAL", "MERGER",
    )
    assert data["threshold_type"] in ("SIMPLE_MAJORITY", "SUPERMAJORITY")
    assert data["status"] in (
        "DRAFT", "PROPOSED", "OPEN", "TABLED", "ADOPTED",
        "REJECTED", "WITHDRAWN", "EXPIRED", "SUPERSEDED",
    )
    assert isinstance(data["eligible_voter_ids"], list)
    assert isinstance(data["recused_physician_ids"], list)


def assert_vote(data: dict):
    _assert_common_fields(data)
    assert data["vote_choice"] in ("FOR", "AGAINST", "ABSTAIN")
    assert data["status"] in ("CAST", "VOIDED")


def assert_capital_call(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("APPROVED", "BILLED", "COLLECTED", "PARTIALLY_DEFAULTED")
    assert isinstance(data["total_amount_cents"], int)


def assert_assessment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("BILLED", "PARTIAL", "PAID", "DELINQUENT", "DEFAULTED")
    assert isinstance(data["assessed_cents"], int)
    assert isinstance(data["late_fee_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert data["total_due_cents"] == data["assessed_cents"] + data["late_fee_cents"]


def assert_distribution(data: dict):
    _assert_common_fields(data)
    assert data["method"] in ("PRO_RATA", "SENIORITY_TIERED")
    assert data["status"] in ("APPROVED", "PAID", "VOIDED")
    assert isinstance(data["allocations"], list)
    for alloc in data["allocations"]:
        assert alloc["status"] in ("PENDING", "PAID", "CLAWED_BACK", "CANCELLED")
        assert isinstance(alloc["allocated_cents"], int)


def assert_exit_valuation(data: dict):
    _assert_common_fields(data)
    assert data["trigger_type"] in ("VOLUNTARY", "RETIREMENT", "TERMINATION", "DEATH")
    assert data["status"] in ("INITIATED", "APPRAISED", "DISPUTED", "ARBITRATION", "FINALIZED")
    assert isinstance(data["dispute_rounds"], int)


def assert_coi_disclosure(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("FILED", "CLEARED", "FLAGGED")
    assert isinstance(data["description"], str) and data["description"]


def assert_merger_proposal(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "PROPOSED", "DUE_DILIGENCE", "NEGOTIATION", "APPROVED", "REJECTED", "TERMINATED"
    )
    assert isinstance(data["exchange_ratio_x1000"], int)
    assert isinstance(data["cash_consideration_cents"], int)


def assert_share_conservation(policy: dict, physicians: list):
    """treasury_shares + sum(shares_held) == total_shares_authorized (PRD §3.1)."""
    total_held = sum(p["shares_held"] for p in physicians)
    assert policy["treasury_shares"] + total_held == policy["total_shares_authorized"], (
        f"Share conservation violated: treasury {policy['treasury_shares']} + "
        f"held {total_held} != authorized {policy['total_shares_authorized']}"
    )


def allocation_for(distribution: dict, physician_id: str) -> dict:
    """Find one physician's allocation entry in a distribution."""
    matches = [a for a in distribution["allocations"] if a["physician_id"] == physician_id]
    assert len(matches) == 1, (
        f"Expected exactly one allocation for physician {physician_id}, "
        f"got {len(matches)}"
    )
    return matches[0]
