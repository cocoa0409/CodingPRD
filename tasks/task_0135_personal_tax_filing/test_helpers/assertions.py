"""Entity assertions and domain invariant checkers.

These check the response shape and domain invariants required by the
PRD contract.

PRD §2.4: every primary resource carries id + created_at + updated_at
+ version EXCEPT EFiling and AuditLog which are lean (id + created_at
only).
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
    """PRD §2.4: 'version is a monotonically increasing integer that
    starts at 1 on creation and increments by exactly 1 on every
    mutation.'"""
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got "
        f"{data.get('version')!r}"
    )


def assert_version_incremented_by_one(
    after: Dict[str, Any], before: Dict[str, Any],
) -> None:
    """PRD §2.4: version increments by exactly 1 on every mutation."""
    assert after["version"] == before["version"] + 1, (
        f"version must increment by 1: before={before['version']}, "
        f"after={after['version']}"
    )


# ---------------------------------------------------------------------------
# Taxpayer — PRD §3.1
# ---------------------------------------------------------------------------
def assert_taxpayer(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("ssn_last4"), str) and (
        len(data["ssn_last4"]) == 4 and data["ssn_last4"].isdigit()
    ), f"ssn_last4 must be exactly 4 digits, got {data.get('ssn_last4')!r}"
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("date_of_birth"), str)
    addr = data.get("filing_address")
    assert isinstance(addr, dict), (
        f"filing_address must be object, got {type(addr).__name__}"
    )
    for key in ("street", "city", "state", "zip"):
        assert key in addr, f"filing_address.{key} missing"
    assert isinstance(data.get("is_blind"), bool), (
        f"is_blind must be bool, got {data.get('is_blind')!r}"
    )
    assert data.get("account_status") in {"ACTIVE", "LOCKED"}, (
        f"account_status must be ACTIVE/LOCKED, got "
        f"{data.get('account_status')!r}"
    )


# ---------------------------------------------------------------------------
# TaxReturn — PRD §3.1 / §3.5 / §3.7
# ---------------------------------------------------------------------------
def assert_tax_return(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("taxpayer_id"), str)
    assert isinstance(data.get("tax_year"), int)
    assert data["tax_year"] >= 2020 and data["tax_year"] <= 2025, (
        f"tax_year must be 2020..2025, got {data['tax_year']}"
    )
    assert data.get("filing_status") in {
        "SINGLE", "MARRIED_JOINT", "MARRIED_SEPARATE",
        "HEAD_OF_HOUSEHOLD", "QUALIFYING_SURVIVING_SPOUSE",
    }
    assert data.get("status") in {
        "DRAFT", "READY_TO_FILE", "FILED", "ACCEPTED",
        "REJECTED", "AMENDED", "SUPERSEDED",
    }
    assert data.get("deduction_method") in {"STANDARD", "ITEMIZED"}
    assert isinstance(data.get("dependents_count"), int)
    assert data["dependents_count"] >= 0
    assert isinstance(data.get("qualifying_children_under_17"), int)
    assert data["qualifying_children_under_17"] >= 0
    # PRD §3.1: qualifying-children count may not exceed dependents.
    assert data["qualifying_children_under_17"] <= data["dependents_count"]
    # Computed fields are integer cents.
    for cents_field in (
        "total_income_cents",
        "agi_cents",
        "taxable_income_cents",
        "regular_tax_cents",
        "amt_cents",
        "total_credits_cents",
        "total_withholding_cents",
        "estimated_payments_applied_cents",
        "balance_due_or_refund_cents",
    ):
        assert cents_field in data, f"missing {cents_field}"
        assert isinstance(data[cents_field], int), (
            f"{cents_field} must be integer, got "
            f"{type(data[cents_field]).__name__}"
        )


# ---------------------------------------------------------------------------
# IncomeDocument — PRD §3.2
# ---------------------------------------------------------------------------
def assert_income_document(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("tax_return_id"), str)
    assert data.get("doc_type") in {
        "W2", "1099_NEC", "1099_INT", "1099_DIV", "1099_B",
    }
    assert isinstance(data.get("payer_ein"), str)
    assert isinstance(data.get("payer_name"), str)
    assert is_iso8601_timestamp(data.get("imported_at", "")), (
        f"imported_at must be ISO 8601, got {data.get('imported_at')!r}"
    )
    for cents in (
        "wages_cents",
        "federal_withholding_cents",
        "nonemployee_comp_cents",
        "interest_income_cents",
        "ordinary_dividends_cents",
        "qualified_dividends_cents",
        "proceeds_cents",
        "cost_basis_cents",
    ):
        assert cents in data, f"missing {cents}"
        assert isinstance(data[cents], int)
    assert data.get("holding_period") in {"NONE", "SHORT_TERM", "LONG_TERM"}


# ---------------------------------------------------------------------------
# Schedule — PRD §3.3
# ---------------------------------------------------------------------------
def assert_schedule(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("tax_return_id"), str)
    assert data.get("schedule_type") in {"A", "B", "C", "D", "E"}
    for cents in (
        "itemized_medical_cents",
        "itemized_salt_cents",
        "itemized_mortgage_interest_cents",
        "itemized_charity_cents",
        "schedule_b_interest_cents",
        "schedule_b_dividends_cents",
        "schedule_c_gross_receipts_cents",
        "schedule_c_expenses_cents",
        "schedule_c_net_profit_cents",
        "schedule_d_short_term_gain_cents",
        "schedule_d_long_term_gain_cents",
        "schedule_e_rental_income_cents",
        "schedule_e_rental_expenses_cents",
        "total_itemized_deduction_cents",
    ):
        assert cents in data, f"missing {cents}"
        assert isinstance(data[cents], int)


# ---------------------------------------------------------------------------
# TaxCredit — PRD §3.4
# ---------------------------------------------------------------------------
def assert_tax_credit(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("tax_return_id"), str)
    assert data.get("credit_type") in {"EITC", "CTC", "AOTC"}
    assert isinstance(data.get("requested_amount_cents"), int)
    assert data.get("eligibility_status") in {
        "PENDING", "ELIGIBLE", "INELIGIBLE",
    }
    assert isinstance(data.get("approved_amount_cents"), int)
    assert isinstance(data.get("refundable_portion_cents"), int)
    assert isinstance(data.get("aotc_student_count"), int)
    assert isinstance(data.get("aotc_qualified_expenses_cents"), int)
    # ineligibility_reason may be null or string per PRD §3.4.
    reason = data.get("ineligibility_reason")
    assert reason is None or isinstance(reason, str)


# ---------------------------------------------------------------------------
# EFiling — PRD §3.8. PRD §2.4: append-style; id + created_at only.
# ---------------------------------------------------------------------------
def assert_efiling(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    assert "updated_at" not in data, (
        "EFiling is append-style and must not expose updated_at "
        "per PRD §2.4"
    )
    assert "version" not in data, (
        "EFiling is append-style and must not expose version "
        "per PRD §2.4"
    )
    assert isinstance(data.get("tax_return_id"), str)
    assert isinstance(data.get("submission_id"), str)
    assert data.get("outcome") in {"PENDING", "ACCEPTED", "REJECTED"}
    assert is_iso8601_timestamp(data.get("filed_at", "")), (
        f"filed_at must be ISO 8601, got {data.get('filed_at')!r}"
    )
    processed = data.get("processed_at")
    if processed is not None:
        assert is_iso8601_timestamp(processed)


# ---------------------------------------------------------------------------
# AmendedReturn — PRD §3.9
# ---------------------------------------------------------------------------
def assert_amended_return(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("original_return_id"), str)
    # PRD §3.9: form_code is fixed at the literal string '1040X'.
    assert data.get("form_code") == "1040X", (
        f"form_code must be '1040X', got {data.get('form_code')!r}"
    )
    assert isinstance(data.get("reason_summary"), str)
    assert data.get("status") in {
        "DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED",
    }
    assert isinstance(data.get("delta_agi_cents"), int)
    assert isinstance(data.get("delta_tax_cents"), int)
    assert isinstance(data.get("delta_balance_due_or_refund_cents"), int)


# ---------------------------------------------------------------------------
# EstimatedTaxPayment — PRD §3.10
# ---------------------------------------------------------------------------
def assert_estimated_payment(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("taxpayer_id"), str)
    assert isinstance(data.get("tax_year"), int)
    assert data.get("quarter") in {"Q1", "Q2", "Q3", "Q4"}
    assert isinstance(data.get("amount_cents"), int)
    assert data["amount_cents"] > 0
    assert isinstance(data.get("scheduled_pay_date"), str)
    assert data.get("status") in {"SCHEDULED", "CONFIRMED", "CANCELLED"}


# ---------------------------------------------------------------------------
# AuditLog — PRD §2.11. PRD §2.4: append-style; id + created_at only.
# ---------------------------------------------------------------------------
def assert_audit_log(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    assert "updated_at" not in data, (
        "AuditLog is append-style and must not expose updated_at "
        "per PRD §2.4"
    )
    assert "version" not in data, (
        "AuditLog is append-style and must not expose version "
        "per PRD §2.4"
    )
    assert isinstance(data.get("actor_role"), str)
    assert isinstance(data.get("actor_id"), str)
    assert isinstance(data.get("action"), str)
    assert isinstance(data.get("target_entity"), str)
    assert isinstance(data.get("target_id"), str)
    assert isinstance(data.get("payload"), dict)


# ---------------------------------------------------------------------------
# Safe-harbor response — PRD §3.10
# ---------------------------------------------------------------------------
def assert_safe_harbor(data: Dict[str, Any]) -> None:
    """PRD §3.10: 'The advisory reports safe_harbor_met as true if the
    payments meet or exceed either threshold, alongside the inputs
    (current_tax_cents, payments_made_cents, threshold_current_cents,
    prior_threshold_cents) that produced the verdict.'"""
    assert "safe_harbor_met" in data
    assert isinstance(data["safe_harbor_met"], bool)
    for cents in (
        "current_tax_cents",
        "payments_made_cents",
        "threshold_current_cents",
    ):
        assert cents in data, f"safe_harbor must expose {cents}"
        assert isinstance(data[cents], int)
    # prior_threshold_cents may be present as int or null (PRD: "when
    # no prior-year accepted or superseded return exists, the prior
    # threshold is treated as unreachable").
    assert "prior_threshold_cents" in data


# ---------------------------------------------------------------------------
# Clock response — PRD §2.9
# ---------------------------------------------------------------------------
def assert_clock_response(data: Dict[str, Any]) -> None:
    assert "now" in data
    assert is_iso8601_timestamp(data["now"])


def assert_clock_advance_response(data: Dict[str, Any]) -> None:
    """PRD §2.9: 'The response of the advance call enumerates every
    transition that fired, listing the affected entity, its id, and
    the from/to state pair.'"""
    assert "now" in data
    assert is_iso8601_timestamp(data["now"])
    assert "advanced_transitions" in data
    assert isinstance(data["advanced_transitions"], list)
    for entry in data["advanced_transitions"]:
        for k in ("entity", "id", "from", "to"):
            assert k in entry, (
                f"clock advance transition must include {k}, "
                f"got keys: {list(entry)}"
            )


__all__ = [
    "assert_version_incremented_by_one",
    "assert_taxpayer",
    "assert_tax_return",
    "assert_income_document",
    "assert_schedule",
    "assert_tax_credit",
    "assert_efiling",
    "assert_amended_return",
    "assert_estimated_payment",
    "assert_audit_log",
    "assert_safe_harbor",
    "assert_clock_response",
    "assert_clock_advance_response",
]
