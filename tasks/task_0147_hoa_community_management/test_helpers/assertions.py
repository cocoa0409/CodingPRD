"""Entity assertions and domain invariant checkers.

These check response shape and domain invariants required by the PRD
contract.

PRD §2.4 — entities split into two shapes:

    common-fields (Unit, Member, AssessmentCharge, ACCRequest, Violation,
    BoardResolution, ElectionCycle, Lien, ReserveStudy):
        id, created_at, updated_at, version

    lean (AssessmentCycle, Payment, ACCVote, Candidate, Ballot):
        id, created_at only
"""
from __future__ import annotations

from typing import Any, Dict, Iterable

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields predicates — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_id_and_created_at(data: Dict[str, Any]) -> None:
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'version starts at 1 and increments by exactly 1 on
    every server-side mutation.'"""
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4 common-fields entities (Unit, Member, AssessmentCharge,
    ACCRequest, Violation, BoardResolution, ElectionCycle, Lien,
    ReserveStudy)."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)


def assert_lean_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4 lean entities (AssessmentCycle, Payment, ACCVote,
    Candidate, Ballot)."""
    _assert_id_and_created_at(data)
    assert "updated_at" not in data or data.get("updated_at") is None, (
        "lean entities must not expose updated_at per PRD §2.4"
    )
    assert "version" not in data or data.get("version") is None, (
        "lean entities must not expose version per PRD §2.4"
    )


def assert_version_incremented_by(
    before: Dict[str, Any], after: Dict[str, Any], delta: int = 1,
) -> None:
    """PRD §2.4: every mutation increments version by exactly 1."""
    assert after["version"] == before["version"] + delta, (
        f"expected version {before['version']}+{delta} = "
        f"{before['version'] + delta}, got {after['version']}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_unit(data: Dict[str, Any]) -> None:
    """PRD §3.1 Unit fields."""
    assert_common_fields(data)
    assert isinstance(data["address"], str) and data["address"]
    assert isinstance(data["owner_member_id"], str) and data["owner_member_id"]
    assert isinstance(data["share_factor"], (int, float))
    assert 0.0001 <= float(data["share_factor"]) <= 1.0000
    # mortgage_holder is optional/nullable
    assert "mortgage_holder" in data
    # PRD §3.1: lien_status enum {NONE, NOTICE_SENT, RECORDED, RELEASED}
    assert data.get("lien_status") in (
        "NONE", "NOTICE_SENT", "RECORDED", "RELEASED",
    ), f"unexpected lien_status: {data.get('lien_status')!r}"


def assert_member(data: Dict[str, Any]) -> None:
    """PRD §3.1 Member fields."""
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    # PRD §3.1: 'eligible_to_vote ... boolean'
    assert isinstance(data["eligible_to_vote"], bool), (
        f"eligible_to_vote must be bool, got "
        f"{type(data['eligible_to_vote']).__name__}"
    )
    assert data["board_role"] in (
        "NONE", "PRESIDENT", "TREASURER", "SECRETARY", "DIRECTOR",
    )
    assert isinstance(data["total_overdue_amount_cents"], int)
    assert data["total_overdue_amount_cents"] >= 0


def assert_assessment_cycle(data: Dict[str, Any]) -> None:
    """PRD §2.4: AssessmentCycle is lean (id + created_at only)."""
    assert_lean_fields(data)
    assert data["cycle_type"] in ("REGULAR", "SPECIAL")
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["due_date"])
    assert isinstance(data["total_levy_cents"], int)
    assert data["total_levy_cents"] >= 100
    # approval_resolution_id optional
    assert "approval_resolution_id" in data
    assert data["status"] in ("DRAFT", "ISSUED", "CLOSED", "VOIDED")


def assert_assessment_charge(data: Dict[str, Any]) -> None:
    """PRD §3.2 AssessmentCharge — common-fields entity."""
    assert_common_fields(data)
    assert isinstance(data["cycle_id"], str) and data["cycle_id"]
    assert isinstance(data["unit_id"], str) and data["unit_id"]
    assert isinstance(data["principal_cents"], int)
    assert data["principal_cents"] >= 0
    assert isinstance(data["late_fee_cents"], int)
    assert data["late_fee_cents"] >= 0
    assert isinstance(data["paid_cents"], int)
    assert data["paid_cents"] >= 0
    assert data["status"] in ("OPEN", "PAID", "OVERDUE", "WRITTEN_OFF")


def assert_payment(data: Dict[str, Any]) -> None:
    """PRD §2.4: Payment is lean (id + created_at only)."""
    assert_lean_fields(data)
    assert isinstance(data["member_id"], str) and data["member_id"]
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] > 0
    # PRD §3.3 allocations array
    assert isinstance(data["allocations"], list)
    if data["allocations"]:
        for alloc in data["allocations"]:
            assert "charge_id" in alloc or "violation_id" in alloc or "target_id" in alloc, (
                f"allocation row missing target id key: {alloc!r}"
            )
            assert "applied_cents" in alloc
            assert isinstance(alloc["applied_cents"], int)
            assert alloc["applied_cents"] >= 0


def assert_payment_allocation_sums(data: Dict[str, Any]) -> None:
    """PRD §3.3: 'The resulting allocations array ... whose applied_cents
    sums to the payment's amount_cents.'"""
    total = sum(int(a["applied_cents"]) for a in data["allocations"])
    assert total == data["amount_cents"], (
        f"allocations sum {total} != amount_cents {data['amount_cents']}"
    )


def assert_acc_request(data: Dict[str, Any]) -> None:
    """PRD §3.4 ACCRequest fields."""
    assert_common_fields(data)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["submitted_by_member_id"], str)
    assert data["category"] in ("APPEARANCE", "LANDSCAPING")
    assert isinstance(data["description"], str)
    assert is_iso8601_timestamp(data["submitted_at"])
    assert is_iso8601_timestamp(data["deemed_decision_deadline"])
    assert data["status"] in (
        "SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED",
        "AUTO_APPROVED", "AUTO_DENIED", "WITHDRAWN",
    )
    assert isinstance(data["yes_votes"], int) and data["yes_votes"] >= 0
    assert isinstance(data["no_votes"], int) and data["no_votes"] >= 0


def assert_acc_vote(data: Dict[str, Any]) -> None:
    """PRD §2.4: ACCVote is lean (id + created_at only)."""
    assert_lean_fields(data)
    assert isinstance(data["request_id"], str)
    assert isinstance(data["voter_member_id"], str)
    assert data["vote"] in ("YES", "NO")
    assert is_iso8601_timestamp(data["cast_at"])


def assert_violation(data: Dict[str, Any]) -> None:
    """PRD §3.5 Violation fields."""
    assert_common_fields(data)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["opened_by_member_id"], str)
    assert is_iso8601_timestamp(data["opened_at"])
    assert is_iso8601_timestamp(data["cure_deadline"])
    assert isinstance(data["occurrence_index"], int)
    assert data["occurrence_index"] >= 1
    assert isinstance(data["fine_cents"], int)
    assert data["fine_cents"] >= 0
    assert data["status"] in ("OPEN", "CURED", "FINED", "WAIVED")


def assert_board_resolution(data: Dict[str, Any]) -> None:
    """PRD §3.8 BoardResolution fields."""
    assert_common_fields(data)
    assert data["subject"] in (
        "SPECIAL_ASSESSMENT", "RESERVE_STUDY_ADOPTION",
        "FINE_WAIVER", "LIEN_RECORDATION", "LIEN_RELEASE",
    )
    assert isinstance(data["target_id"], str) and data["target_id"]
    assert isinstance(data["yes_votes"], int) and data["yes_votes"] >= 0
    assert isinstance(data["no_votes"], int) and data["no_votes"] >= 0
    assert data["status"] in ("PROPOSED", "PASSED", "FAILED", "EXECUTED")


def assert_election_cycle(data: Dict[str, Any]) -> None:
    """PRD §3.7 ElectionCycle fields."""
    assert_common_fields(data)
    assert data["seat"] in (
        "PRESIDENT", "TREASURER", "SECRETARY", "DIRECTOR",
    )
    assert is_iso8601_timestamp(data["nomination_open_at"])
    assert is_iso8601_timestamp(data["voting_open_at"])
    assert is_iso8601_timestamp(data["voting_close_at"])
    assert isinstance(data["quorum_pct"], (int, float))
    assert 0.10 <= float(data["quorum_pct"]) <= 1.00
    assert data["status"] in (
        "NOMINATION", "VOTING", "TALLIED", "CERTIFIED",
        "FAILED_QUORUM", "VOIDED",
    )
    # eligible_voter_count_at_open is null until VOTING opens
    assert "eligible_voter_count_at_open" in data
    assert "winner_candidate_id" in data


def assert_candidate(data: Dict[str, Any]) -> None:
    """PRD §2.4: Candidate is lean (id + created_at only)."""
    assert_lean_fields(data)
    assert isinstance(data["election_id"], str)
    assert isinstance(data["member_id"], str)
    assert is_iso8601_timestamp(data["nominated_at"])
    assert isinstance(data["vote_count"], int) and data["vote_count"] >= 0


def assert_ballot(data: Dict[str, Any]) -> None:
    """PRD §2.4: Ballot is lean (id + created_at only)."""
    assert_lean_fields(data)
    assert isinstance(data["election_id"], str)
    assert isinstance(data["voter_member_id"], str)
    assert isinstance(data["candidate_id"], str)


def assert_lien(data: Dict[str, Any]) -> None:
    """PRD §3.6 Lien fields."""
    assert_common_fields(data)
    assert isinstance(data["unit_id"], str)
    assert data["status"] in ("NOTICE_SENT", "RECORDED", "RELEASED")
    # PRD §3.6: 'principal_cents_at_record and mortgage_holder_at_record
    # are populated only at recordation.'
    assert "principal_cents_at_record" in data
    assert "mortgage_holder_at_record" in data
    assert "recorded_at" in data
    assert "released_at" in data


def assert_reserve_study(data: Dict[str, Any]) -> None:
    """PRD §3.9 ReserveStudy fields."""
    assert_common_fields(data)
    assert isinstance(data["study_year"], int)
    assert isinstance(data["components"], list)
    assert len(data["components"]) >= 1
    assert isinstance(data["current_reserve_balance_cents"], int)
    assert isinstance(data["full_funding_target_cents"], int)
    # funded_ratio may be null when target is zero (PRD §3.9)
    assert "funded_ratio" in data
    assert data["posture"] in (
        "OK", "RESTRICTED", "SPECIAL_ASSESSMENT_REQUIRED",
    )
    assert "adopted_resolution_id" in data
    assert data["status"] in ("DRAFT", "ADOPTED", "SUPERSEDED")


# ---------------------------------------------------------------------------
# Conservation invariants — PRD §3.2, §3.3, §2.8
# ---------------------------------------------------------------------------
def assert_principal_sum_matches_levy(
    charges: Iterable[Dict[str, Any]], total_levy_cents: int,
) -> None:
    """PRD §3.2: 'This guarantees that the sum of principal_cents across
    all newly created charges equals total_levy_cents exactly.'"""
    total = sum(int(c["principal_cents"]) for c in charges)
    assert total == total_levy_cents, (
        f"sum(principal_cents) = {total} != total_levy_cents "
        f"{total_levy_cents}"
    )


def assert_total_overdue(member: Dict[str, Any], expected_cents: int) -> None:
    """PRD §2.8: 'A single source-of-truth aggregate,
    Member.total_overdue_amount_cents'."""
    actual = int(member["total_overdue_amount_cents"])
    assert actual == expected_cents, (
        f"Member.total_overdue_amount_cents = {actual} != expected "
        f"{expected_cents}"
    )


__all__ = [
    "assert_common_fields",
    "assert_lean_fields",
    "assert_version_incremented_by",
    "assert_unit",
    "assert_member",
    "assert_assessment_cycle",
    "assert_assessment_charge",
    "assert_payment",
    "assert_payment_allocation_sums",
    "assert_acc_request",
    "assert_acc_vote",
    "assert_violation",
    "assert_board_resolution",
    "assert_election_cycle",
    "assert_candidate",
    "assert_ballot",
    "assert_lien",
    "assert_reserve_study",
    "assert_principal_sum_matches_levy",
    "assert_total_overdue",
]
