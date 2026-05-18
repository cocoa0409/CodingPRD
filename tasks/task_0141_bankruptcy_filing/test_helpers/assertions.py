"""Entity assertions and domain invariant checkers.

These check response shape and domain invariants required by the
PRD contract. They are intentionally generous about server-minted
fields: a test that wants to pin a specific computed value asserts it
directly in test code.

PRD §2.4: every persisted resource carries id and created_at. The
mutable entities — Debtor, Case, Creditor, Claim, Plan — additionally
carry updated_at and version. Schedule, MeansTestResult,
TrusteePayment, and CollectionAction are lean (id + created_at only).
"""
from __future__ import annotations

from typing import Any, Dict, List

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
    """PRD §2.4: 'version (an integer initialized to 1 and incremented
    by exactly one on every mutation)'."""
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got "
        f"{data.get('version')!r}"
    )


# ---------------------------------------------------------------------------
# Debtor — PRD §3.1
# ---------------------------------------------------------------------------
def assert_debtor(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("household_size"), int)
    # PRD §3.1: 'household_size (which must be at least 1 ...)'.
    assert data["household_size"] >= 1
    # PRD §3.1: 'state_code consisting of exactly two uppercase letters'.
    sc = data.get("state_code")
    assert isinstance(sc, str) and len(sc) == 2 and sc.isupper(), (
        f"state_code must be 2 upper letters, got {sc!r}"
    )
    assert isinstance(data.get("total_cases_filed"), int)
    assert data["total_cases_filed"] >= 0


# ---------------------------------------------------------------------------
# Creditor — PRD §3.1
# ---------------------------------------------------------------------------
def assert_creditor(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("name"), str) and data["name"]
    assert data.get("creditor_type") in {
        "SECURED", "PRIORITY", "GENERAL_UNSECURED",
    }, f"creditor_type invalid: {data.get('creditor_type')!r}"


# ---------------------------------------------------------------------------
# Case — PRD §3.1 / §3.4
# ---------------------------------------------------------------------------
def assert_case(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("debtor_id", ""))
    assert data.get("chapter_requested") in {"CHAPTER_7", "CHAPTER_13"}
    # chapter_effective is null until file_case commits.
    ce = data.get("chapter_effective")
    assert ce is None or ce in {"CHAPTER_7", "CHAPTER_13"}
    assert data.get("status") in {
        "DRAFT", "FILED", "MEETING_SCHEDULED", "MEETING_HELD",
        "PLAN_PROPOSED", "PLAN_CONFIRMED", "IN_REPAYMENT",
        "DISCHARGED", "DISMISSED", "WITHDRAWN_PRE_FILE",
    }
    assert isinstance(data.get("automatic_stay_active"), bool)
    # schedule_completeness is an array of missing letters.
    assert isinstance(data.get("schedule_completeness"), list)
    for letter in data["schedule_completeness"]:
        assert letter in {
            "A", "B", "C", "D", "E", "F", "G", "H", "I", "J",
        }, f"unexpected letter in schedule_completeness: {letter!r}"
    assert isinstance(data.get("total_unsecured_pool_cents"), int)
    assert data["total_unsecured_pool_cents"] >= 0


# ---------------------------------------------------------------------------
# Schedule — PRD §3.2 / §2.4 lean entity
# ---------------------------------------------------------------------------
def assert_schedule(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # PRD §2.4: 'each Schedule carries only id and created_at;
    # updated_at and version are absent'. So we intentionally do NOT
    # assert updated_at/version here.
    assert data.get("schedule_type") in {
        "A", "B", "C", "D", "E", "F", "G", "H", "I", "J",
    }
    assert isinstance(data.get("line_items"), list)
    assert isinstance(data.get("total_cents"), int)
    # superseded_by_id is null on the active row.


# ---------------------------------------------------------------------------
# MeansTestResult — PRD §3.3 / §2.4 lean entity
# ---------------------------------------------------------------------------
def assert_means_test_result(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # PRD §2.4: 'MeansTestResult rows are immutable computation
    # snapshots and likewise carry only id and created_at'.
    assert is_valid_uuid(data.get("case_id", ""))
    for field in (
        "current_monthly_income_cents",
        "cmi_annualized_cents",
        "state_median_annual_cents",
        "allowed_monthly_expenses_cents",
        "disposable_monthly_income_cents",
        "required_plan_months",
        "minimum_plan_total_cents",
    ):
        assert isinstance(data.get(field), int), (
            f"{field} must be integer, got {data.get(field)!r}"
        )
        assert data[field] >= 0, f"{field} must be >= 0, got {data[field]}"
    assert isinstance(data.get("presumption_of_abuse"), bool)
    # PRD §3.3: 'required_plan_months is 36 when presumption_of_abuse is
    # false and 60 when presumption_of_abuse is true.'
    if data["presumption_of_abuse"]:
        assert data["required_plan_months"] == 60
    else:
        assert data["required_plan_months"] == 36


# ---------------------------------------------------------------------------
# Claim — PRD §3.6
# ---------------------------------------------------------------------------
def assert_claim(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert is_valid_uuid(data.get("creditor_id", ""))
    assert data.get("claim_class") in {
        "SECURED", "PRIORITY", "GENERAL_UNSECURED",
    }
    assert isinstance(data.get("amount_cents"), int)
    # PRD §3.6: 'amount_cents must be strictly greater than zero'.
    assert data["amount_cents"] > 0
    assert isinstance(data.get("is_dischargeable"), bool)
    assert data.get("status") in {
        "FILED", "ALLOWED", "DISALLOWED", "DISCHARGED",
        "NON_DISCHARGEABLE_REMAINS",
    }


# ---------------------------------------------------------------------------
# Plan — PRD §3.8
# ---------------------------------------------------------------------------
def assert_plan(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("case_id", ""))
    for field in (
        "proposed_monthly_payment_cents",
        "plan_months",
        "planned_total_cents",
        "paid_to_date_cents",
        "missed_payment_count",
    ):
        assert isinstance(data.get(field), int), (
            f"{field} must be integer, got {data.get(field)!r}"
        )
        assert data[field] >= 0
    # PRD §3.8: 'planned_total_cents as the product of
    # proposed_monthly_payment_cents and plan_months'.
    assert (
        data["planned_total_cents"]
        == data["proposed_monthly_payment_cents"] * data["plan_months"]
    ), (
        f"planned_total_cents must equal "
        f"proposed_monthly_payment_cents * plan_months; got "
        f"{data['planned_total_cents']} != "
        f"{data['proposed_monthly_payment_cents']} * "
        f"{data['plan_months']}"
    )
    assert data.get("status") in {
        "PROPOSED", "CONFIRMED", "COMPLETED", "DEFAULTED", "WITHDRAWN",
    }


# ---------------------------------------------------------------------------
# TrusteePayment — PRD §3.9 / §2.4 lean entity
# ---------------------------------------------------------------------------
def assert_trustee_payment(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # PRD §2.4: 'TrusteePayment rows are append-only ledger entries and
    # carry only id and created_at'.
    assert is_valid_uuid(data.get("plan_id", ""))
    assert isinstance(data.get("sequence_number"), int)
    assert data["sequence_number"] >= 1
    assert isinstance(data.get("amount_cents"), int)
    assert data.get("status") in {"APPLIED", "MISSED"}
    assert isinstance(data.get("applied_at"), str)
    assert is_iso8601_timestamp(data["applied_at"])


# ---------------------------------------------------------------------------
# CollectionAction — PRD §2.7 / §2.4 lean entity
# ---------------------------------------------------------------------------
def assert_collection_action(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # PRD §2.4: 'CollectionAction rows are immutable attempt logs born
    # in their final outcome and carry only id and created_at as their
    # bookkeeping fields'.
    assert is_valid_uuid(data.get("creditor_id", ""))
    assert is_valid_uuid(data.get("case_id", ""))
    assert data.get("action_kind") in {
        "GARNISH", "LIEN", "LAWSUIT", "DUNNING_LETTER",
    }
    assert data.get("outcome") in {"PROCESSED", "REJECTED_STAY"}
    # PRD §2.7: 'rejected_reason is written as the string
    # AUTOMATIC_STAY_ACTIVE ... rejected_reason is the empty string'
    # when PROCESSED.
    rr = data.get("rejected_reason")
    assert isinstance(rr, str)
    if data["outcome"] == "REJECTED_STAY":
        assert rr == "AUTOMATIC_STAY_ACTIVE", (
            f"rejected_reason must be 'AUTOMATIC_STAY_ACTIVE' for "
            f"REJECTED_STAY outcome, got {rr!r}"
        )
    else:
        assert rr == "", (
            f"rejected_reason must be empty for PROCESSED outcome, "
            f"got {rr!r}"
        )


# ---------------------------------------------------------------------------
# Version-bump invariant — PRD §2.4 / §2.10
# ---------------------------------------------------------------------------
def assert_version_incremented_by_one(after: Dict[str, Any],
                                      before_version: int) -> None:
    """PRD §2.4: 'version (an integer initialized to 1 and incremented
    by exactly one on every mutation)'.
    """
    assert after["version"] == before_version + 1, (
        f"expected version {before_version + 1}, got {after['version']}"
    )


# ---------------------------------------------------------------------------
# Discharge partition invariant — PRD §3.7 / §3.10
# ---------------------------------------------------------------------------
def assert_discharge_partition_total_preserved(
    pre_allowed_total_cents: int,
    post_claims: List[Dict[str, Any]],
) -> None:
    """PRD §3.7: 'The partition is total — the sum of amount_cents
    across all claims that were ALLOWED immediately before the
    discharge equals the sum across the two terminal buckets after,
    with no claim left in ALLOWED.'
    """
    post_total = sum(
        c["amount_cents"] for c in post_claims
        if c["status"] in {"DISCHARGED", "NON_DISCHARGEABLE_REMAINS"}
    )
    assert post_total == pre_allowed_total_cents, (
        f"discharge partition must preserve total; pre={pre_allowed_total_cents}, "
        f"post={post_total}"
    )
    # No claim left in ALLOWED.
    for c in post_claims:
        assert c["status"] != "ALLOWED", (
            f"claim {c.get('id')} still ALLOWED after discharge"
        )


# ---------------------------------------------------------------------------
# Waterfall invariant — PRD §3.10
# ---------------------------------------------------------------------------
def assert_waterfall_sum_equals_pool(
    *, admin_fee_cents: int,
    priority_takes_cents: int,
    secured_takes_cents: int,
    unsecured_shares_cents: int,
    pool_cents: int,
) -> None:
    """PRD §3.10: 'The invariant maintained across the four buckets is
    that the administrative fee plus the priority takes plus the
    secured takes plus the unsecured shares equals exactly
    Plan.paid_to_date_cents — no cent is lost and none is invented.'
    """
    actual = (
        admin_fee_cents + priority_takes_cents
        + secured_takes_cents + unsecured_shares_cents
    )
    assert actual == pool_cents, (
        f"waterfall sum must equal pool; got "
        f"admin={admin_fee_cents} + priority={priority_takes_cents} + "
        f"secured={secured_takes_cents} + unsecured="
        f"{unsecured_shares_cents} = {actual}, but pool={pool_cents}"
    )


__all__ = [
    "assert_debtor",
    "assert_creditor",
    "assert_case",
    "assert_schedule",
    "assert_means_test_result",
    "assert_claim",
    "assert_plan",
    "assert_trustee_payment",
    "assert_collection_action",
    "assert_version_incremented_by_one",
    "assert_discharge_partition_total_preserved",
    "assert_waterfall_sum_equals_pool",
]
