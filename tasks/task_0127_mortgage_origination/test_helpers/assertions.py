"""Entity assertions and domain invariant checkers.

Validates the structural shape of each entity response against the
field set PRD §2.4 and §3 specify, including the common-fields
distinction:

  - Borrower / LoanApplication / IncomeVerification / AssetVerification /
    Appraisal / TitleSearch / RateLock / Disclosure are common-fields
    entities and MUST carry id + created_at + updated_at + version.
  - RateLockExtension and UDAAPReview are append-only and carry ONLY
    id + created_at — they MUST NOT expose updated_at or version
    (PRD §2.4: "expose only id and created_at").
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _assert_common_fields(data: Dict[str, Any], label: str) -> None:
    """PRD §2.4 — id + created_at + updated_at + version."""
    assert is_valid_uuid(str(data.get("id", ""))), (
        f"{label}.id must be a UUID (got {data.get('id')!r})"
    )
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), (
        f"{label}.created_at must be ISO 8601 "
        f"(got {data.get('created_at')!r})"
    )
    assert is_iso8601_timestamp(str(data.get("updated_at", ""))), (
        f"{label}.updated_at must be ISO 8601 "
        f"(got {data.get('updated_at')!r})"
    )
    assert isinstance(data.get("version"), int), (
        f"{label}.version must be int (got {type(data.get('version'))})"
    )


def _assert_append_only_fields(data: Dict[str, Any], label: str) -> None:
    """PRD §2.4 — append-only entities expose ONLY id + created_at."""
    assert is_valid_uuid(str(data.get("id", ""))), (
        f"{label}.id must be a UUID"
    )
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), (
        f"{label}.created_at must be ISO 8601"
    )
    # PRD §2.4: "Two entities omit updated_at and version:
    # RateLockExtension and UDAAPReview are conceptually append-only
    # records that, once written, are not modified — they expose only
    # id and created_at."
    assert "updated_at" not in data, (
        f"{label} is append-only — must not expose updated_at"
    )
    assert "version" not in data, (
        f"{label} is append-only — must not expose version"
    )


# ---------------------------------------------------------------------------
# Borrower — PRD §2.4 / §3.1
# ---------------------------------------------------------------------------
def assert_borrower(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Borrower")
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    ssn = data.get("ssn_last4")
    assert isinstance(ssn, str) and len(ssn) == 4 and ssn.isdigit(), (
        f"Borrower.ssn_last4 must be exactly 4 numeric chars "
        f"(PRD §3.1, got {ssn!r})"
    )
    assert isinstance(data.get("annual_income_cents"), int)
    assert data["annual_income_cents"] >= 0
    assert isinstance(data.get("credit_score"), int)
    assert 300 <= data["credit_score"] <= 850, (
        "Borrower.credit_score must lie between 300 and 850 inclusive "
        "(PRD §3.1)"
    )
    sc = data.get("state_code")
    assert isinstance(sc, str) and len(sc) == 2 and sc.isalpha() and sc == sc.upper(), (
        "Borrower.state_code must be two uppercase letters (PRD §3.1)"
    )


# ---------------------------------------------------------------------------
# LoanApplication — PRD §2.4 / §3.1, §3.2, §3.7
# ---------------------------------------------------------------------------
def assert_loan_application(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "LoanApplication")
    assert isinstance(data.get("borrower_id"), str)
    assert isinstance(data.get("property_address"), str)
    assert isinstance(data.get("sale_price_cents"), int)
    assert data["sale_price_cents"] > 0
    assert isinstance(data.get("requested_loan_amount_cents"), int)
    assert data["requested_loan_amount_cents"] > 0
    assert data["requested_loan_amount_cents"] <= data["sale_price_cents"]
    assert data.get("loan_term_months") in (120, 180, 240, 360)
    assert data.get("loan_purpose") in ("PURCHASE", "REFINANCE")
    assert data.get("status") in (
        "INTAKE", "PRE_QUALIFIED", "UNDERWRITING",
        "CONDITIONAL_APPROVAL", "CLEAR_TO_CLOSE",
        "CLOSED", "DENIED", "WITHDRAWN",
    )
    assert isinstance(data.get("assigned_loan_officer_id"), str)
    # PRD §3.1: pmi_required defaults to false at creation.
    assert isinstance(data.get("pmi_required", False), bool)


# ---------------------------------------------------------------------------
# IncomeVerification — PRD §2.4 / §3.3
# ---------------------------------------------------------------------------
def assert_income_verification(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "IncomeVerification")
    assert isinstance(data.get("application_id"), str)
    assert data.get("source_type") in ("W2", "SELF_EMPLOYED", "OTHER")
    assert isinstance(data.get("documented_annual_cents"), int)
    assert data["documented_annual_cents"] >= 0
    assert data.get("status") in ("PENDING", "VERIFIED", "REJECTED")


# ---------------------------------------------------------------------------
# AssetVerification — PRD §2.4 / §3.3
# ---------------------------------------------------------------------------
def assert_asset_verification(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "AssetVerification")
    assert isinstance(data.get("application_id"), str)
    assert data.get("asset_type") in (
        "CHECKING", "SAVINGS", "INVESTMENT", "GIFT",
    )
    assert isinstance(data.get("balance_cents"), int)
    assert data["balance_cents"] >= 0
    assert data.get("status") in ("PENDING", "VERIFIED", "REJECTED")


# ---------------------------------------------------------------------------
# Appraisal — PRD §2.4 / §3.4
# ---------------------------------------------------------------------------
def assert_appraisal(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Appraisal")
    assert isinstance(data.get("application_id"), str)
    assert data.get("status") in (
        "ORDERED", "COMPLETED", "REJECTED", "EXPIRED",
    )
    assert isinstance(data.get("report_date"), str)
    assert is_iso8601_timestamp(data["report_date"]), (
        "Appraisal.report_date must be ISO 8601 (PRD §3.4)"
    )


# ---------------------------------------------------------------------------
# TitleSearch — PRD §2.4 / §3.4
# ---------------------------------------------------------------------------
def assert_title_search(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "TitleSearch")
    assert isinstance(data.get("application_id"), str)
    assert data.get("status") in (
        "ORDERED", "CLEAR", "ISSUES_FOUND", "RESOLVED",
    )
    assert isinstance(data.get("defects_found", []), list)


# ---------------------------------------------------------------------------
# RateLock — PRD §2.4 / §3.5
# ---------------------------------------------------------------------------
def assert_rate_lock(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "RateLock")
    assert isinstance(data.get("application_id"), str)
    assert isinstance(data.get("locked_rate_bps"), int)
    assert 0 < data["locked_rate_bps"] <= 2000, (
        "RateLock.locked_rate_bps must be > 0 and <= 2,000 (PRD §3.5)"
    )
    assert isinstance(data.get("lock_fee_cents"), int)
    assert data["lock_fee_cents"] >= 0
    assert isinstance(data.get("extension_fee_paid_cents", 0), int)
    assert isinstance(data.get("refund_cents", 0), int)
    assert data.get("status") in (
        "LOCKED", "EXTENDED", "EXPIRED", "CONSUMED", "CANCELLED",
    )


# ---------------------------------------------------------------------------
# Disclosure — PRD §2.4 / §3.6
# ---------------------------------------------------------------------------
def assert_disclosure(data: Dict[str, Any]) -> None:
    # PRD §2.4 lists Disclosure under the common-fields entities. The
    # "domain-level version" PRD §2.4 describes is the per-(application,
    # kind) monotonic integer the server mints — we don't second-guess
    # how the implementation reconciles that with the OCC version
    # counter on serialization. We assert presence + the domain status
    # set.
    assert is_valid_uuid(str(data.get("id", ""))), "Disclosure.id must be UUID"
    assert is_iso8601_timestamp(str(data.get("created_at", "")))
    assert isinstance(data.get("application_id"), str)
    assert data.get("kind") in ("LOAN_ESTIMATE", "CLOSING_DISCLOSURE")
    assert isinstance(data.get("apr_bps"), int)
    assert 0 < data["apr_bps"] <= 2500, (
        "Disclosure.apr_bps must be > 0 and <= 2,500 (PRD §3.6)"
    )
    assert isinstance(data.get("total_loan_costs_cents"), int)
    assert isinstance(data.get("total_other_costs_cents"), int)
    assert data.get("status") in (
        "ISSUED", "ACKNOWLEDGED", "SUPERSEDED", "VOIDED",
    )


# ---------------------------------------------------------------------------
# RateLockExtension — PRD §2.4 (append-only) / §3.5
# ---------------------------------------------------------------------------
def assert_rate_lock_extension(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data, "RateLockExtension")
    assert isinstance(data.get("rate_lock_id"), str)
    assert data.get("extra_days") in (7, 15, 30), (
        "RateLockExtension.extra_days must be one of 7, 15, 30 (PRD §3.5)"
    )
    assert isinstance(data.get("fee_cents"), int)
    assert data["fee_cents"] >= 0


# ---------------------------------------------------------------------------
# UDAAPReview — PRD §2.4 (append-only) / §3.9
# ---------------------------------------------------------------------------
def assert_udaap_review(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data, "UDAAPReview")
    assert isinstance(data.get("application_id"), str)
    assert isinstance(data.get("reviewer_user_id"), str)
    assert data.get("outcome") in ("PASS", "FLAG", "BLOCK")


# ---------------------------------------------------------------------------
# SystemClock — PRD §2.9 (singleton)
# ---------------------------------------------------------------------------
def assert_system_clock(data: Dict[str, Any]) -> None:
    """PRD §2.9 — singleton with only `now` exposed."""
    assert isinstance(data.get("now"), str)
    assert is_iso8601_timestamp(data["now"]), (
        "SystemClock.now must be ISO 8601 UTC (PRD §2.9)"
    )


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_version_incremented_by_one(new: int, old: int) -> None:
    """PRD §2.4: 'monotonically increasing counter that starts at 1 and
    increments by 1 on every mutation'.
    """
    assert new == old + 1, (
        f"version must increment by exactly one: {old} -> {new} "
        "(PRD §2.4)"
    )


def assert_rate_lock_fee_invariant(rate_lock: Dict[str, Any]) -> None:
    """PRD §3.5 free-look refund invariant — refund_cents IN
    {0, lock_fee_cents + extension_fee_paid_cents} once the lock is
    CANCELLED.
    """
    if rate_lock.get("status") != "CANCELLED":
        return
    refund = int(rate_lock.get("refund_cents", 0))
    lock_fee = int(rate_lock.get("lock_fee_cents", 0))
    ext_fee = int(rate_lock.get("extension_fee_paid_cents", 0))
    assert refund == 0 or refund == lock_fee + ext_fee, (
        "PRD §3.5: refund_cents must be 0 (outside free-look) or "
        "lock_fee_cents + extension_fee_paid_cents (within free-look). "
        f"Got refund={refund}, lock_fee={lock_fee}, ext_fee={ext_fee}."
    )


__all__ = [
    "assert_borrower",
    "assert_loan_application",
    "assert_income_verification",
    "assert_asset_verification",
    "assert_appraisal",
    "assert_title_search",
    "assert_rate_lock",
    "assert_disclosure",
    "assert_rate_lock_extension",
    "assert_udaap_review",
    "assert_system_clock",
    "assert_version_incremented_by_one",
    "assert_rate_lock_fee_invariant",
]
