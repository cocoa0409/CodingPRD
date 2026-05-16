"""Entity assertions and domain invariant checkers.

These check the response shape and domain invariants required by the PRD
contract. They are intentionally generous about server-minted fields
(e.g., computed counters): a test that wants to pin a specific computed
value asserts it directly in test code.
"""
from __future__ import annotations

from typing import Any, Dict

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
    """PRD §2.4 four common properties: id, created_at, updated_at,
    version. Asserted for entities that carry version (i.e., NOT
    ParentChildLink or PayoutBatch)."""
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


# ---------------------------------------------------------------------------
# Tutor — PRD §3.1
# ---------------------------------------------------------------------------
def assert_tutor(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("display_name"), str) and data["display_name"]
    assert isinstance(data.get("email"), str) and "@" in data["email"]
    assert isinstance(data.get("hourly_rate_cents"), int)
    assert isinstance(data.get("trial_rate_cents"), int)
    # PRD §3.1: trial_rate_cents must be <= hourly_rate_cents.
    assert data["trial_rate_cents"] <= data["hourly_rate_cents"]
    assert data.get("verification_status") in {
        "UNVERIFIED", "PENDING_REVIEW", "VERIFIED", "REJECTED", "SUSPENDED",
    }
    assert isinstance(data.get("subject_tags"), list)
    for t in data["subject_tags"]:
        assert isinstance(t, str)
    assert (
        isinstance(data.get("payout_balance_cents"), int)
        and data["payout_balance_cents"] >= 0
    )
    assert (
        isinstance(data.get("lifetime_completed_sessions"), int)
        and data["lifetime_completed_sessions"] >= 0
    )


# ---------------------------------------------------------------------------
# Student — PRD §3.3
# ---------------------------------------------------------------------------
def assert_student(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("display_name"), str) and data["display_name"]
    assert isinstance(data.get("email"), str) and "@" in data["email"]
    assert data.get("account_type") in {"ADULT", "MINOR"}
    if data["account_type"] == "ADULT":
        # PRD §3.3: "For an ADULT student the parent_id must be null".
        assert data.get("parent_id") in (None, "")
    else:
        # PRD §3.3: "for a MINOR student the parent_id must be set".
        assert data.get("parent_id") is not None
        assert is_valid_uuid(data["parent_id"])
    assert (
        isinstance(data.get("credit_balance_cents"), int)
        and data["credit_balance_cents"] >= 0
    )


# ---------------------------------------------------------------------------
# Parent — PRD §3.3
# ---------------------------------------------------------------------------
def assert_parent(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("display_name"), str) and data["display_name"]
    assert isinstance(data.get("email"), str) and "@" in data["email"]
    assert (
        isinstance(data.get("managed_child_count"), int)
        and data["managed_child_count"] >= 0
    )


# ---------------------------------------------------------------------------
# Credential — PRD §3.1
# ---------------------------------------------------------------------------
def assert_credential(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("tutor_id", ""))
    assert data.get("credential_type") in {
        "GOVERNMENT_ID", "DEGREE", "TEACHING_LICENSE", "BACKGROUND_CHECK",
    }
    assert isinstance(data.get("document_ref"), str)
    assert data.get("status") in {
        "SUBMITTED", "APPROVED", "REJECTED", "EXPIRED",
    }


# ---------------------------------------------------------------------------
# SubjectTag — PRD §3.2
# ---------------------------------------------------------------------------
def assert_subject_tag(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("tutor_id", ""))
    assert isinstance(data.get("subject_code"), str)
    assert data.get("proficiency_level") in {
        "BEGINNER", "INTERMEDIATE", "ADVANCED", "EXPERT",
    }
    assert data.get("status") in {"PROPOSED", "APPROVED", "REMOVED"}


# ---------------------------------------------------------------------------
# Session — PRD §3.4 - §3.8
# ---------------------------------------------------------------------------
def assert_session(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("tutor_id", ""))
    assert is_valid_uuid(data.get("student_id", ""))
    assert isinstance(data.get("subject_code"), str)
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    assert isinstance(data.get("is_trial"), bool)
    assert data.get("status") in {
        "REQUESTED", "CONFIRMED", "IN_PROGRESS", "COMPLETED",
        "CANCELLED_BY_STUDENT", "CANCELLED_BY_TUTOR",
        "DISPUTED", "REFUNDED", "SETTLED",
    }
    # PRD §2.8: money fields are integer cents.
    for field in (
        "gross_price_cents", "credit_applied_cents",
        "charged_amount_cents", "provisional_commission_cents",
        "cancellation_fee_cents", "refund_to_student_cents",
    ):
        assert isinstance(data.get(field), int), (
            f"{field} must be an integer, got {data.get(field)!r}"
        )
        assert data[field] >= 0, (
            f"{field} must be >= 0, got {data[field]}"
        )
    # PRD §3.4: charged_amount_cents = gross_price_cents - credit_applied_cents
    assert (
        data["charged_amount_cents"]
        == data["gross_price_cents"] - data["credit_applied_cents"]
    ), (
        f"charged_amount_cents ({data['charged_amount_cents']}) must equal "
        f"gross_price_cents ({data['gross_price_cents']}) - "
        f"credit_applied_cents ({data['credit_applied_cents']})"
    )


def assert_money_conservation_invariant(data: Dict[str, Any]) -> None:
    """PRD §2.9: "gross_price_cents equals tutor_payout_cents plus
    final_commission_cents plus refund_to_student_cents."

    Asserted at the close of every terminal transition (COMPLETED,
    SETTLED, REFUNDED, CANCELLED_BY_STUDENT, CANCELLED_BY_TUTOR).
    """
    gross = data["gross_price_cents"]
    payout = data.get("tutor_payout_cents", 0) or 0
    commission = data.get("final_commission_cents", 0) or 0
    refund = data.get("refund_to_student_cents", 0) or 0
    assert gross == payout + commission + refund, (
        f"money conservation violated: gross={gross}, "
        f"payout={payout}, commission={commission}, refund={refund} "
        f"(sum={payout + commission + refund})"
    )


# ---------------------------------------------------------------------------
# RefundDispute — PRD §3.7
# ---------------------------------------------------------------------------
def assert_refund_dispute(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("session_id", ""))
    assert data.get("opened_by_role") in {"Student", "Parent"}
    assert isinstance(data.get("opened_by_user_id"), str)
    assert data.get("reason_code") in {
        "TUTOR_NO_SHOW", "QUALITY_ISSUE", "TECHNICAL_FAILURE", "OTHER",
    }
    assert (
        isinstance(data.get("requested_amount_cents"), int)
        and data["requested_amount_cents"] > 0
    )
    assert data.get("status") in {
        "OPEN", "TUTOR_RESPONDED", "COUNTER_PROPOSED", "ARBITRATION",
        "RESOLVED_REFUND", "RESOLVED_DENY", "WITHDRAWN",
    }
    assert (
        isinstance(data.get("round_count"), int)
        and data["round_count"] >= 0
    )


# ---------------------------------------------------------------------------
# ParentChildLink — bookkeeping, id + created_at ONLY per PRD §2.4
# ---------------------------------------------------------------------------
def assert_parent_child_link(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # PRD §2.4: ParentChildLink does NOT carry updated_at or version.
    assert is_valid_uuid(data.get("parent_id", ""))
    assert is_valid_uuid(data.get("student_id", ""))
    assert data.get("link_status") in {
        "PENDING_PARENT_APPROVAL", "ACTIVE", "REVOKED",
    }


# ---------------------------------------------------------------------------
# PayoutBatch — bookkeeping, id + created_at ONLY per PRD §2.4
# ---------------------------------------------------------------------------
def assert_payout_batch(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # PRD §2.4: PayoutBatch does NOT carry updated_at or version.
    assert is_valid_uuid(data.get("tutor_id", ""))
    assert data.get("status") in {"REQUESTED", "PAID", "REVERSED"}
    assert (
        isinstance(data.get("amount_cents"), int)
        and data["amount_cents"] >= 0
    )
    assert isinstance(data.get("session_ids"), list)
    for sid in data["session_ids"]:
        assert is_valid_uuid(sid)
    assert isinstance(data.get("requested_by"), str)


# ---------------------------------------------------------------------------
# Version bump invariant
# ---------------------------------------------------------------------------
def assert_version_incremented_by_one(after: Dict[str, Any],
                                      before_version: int) -> None:
    """PRD §2.4: version starts at 1 and increments by 1 on every
    mutation."""
    assert after["version"] == before_version + 1, (
        f"expected version {before_version + 1}, got {after['version']}"
    )


__all__ = [
    "assert_tutor",
    "assert_student",
    "assert_parent",
    "assert_credential",
    "assert_subject_tag",
    "assert_session",
    "assert_money_conservation_invariant",
    "assert_refund_dispute",
    "assert_parent_child_link",
    "assert_payout_batch",
    "assert_version_incremented_by_one",
]
