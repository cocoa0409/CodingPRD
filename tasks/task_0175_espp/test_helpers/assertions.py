"""Entity assertions and domain invariant checkers.

`assert_{entity}(data)` walks the field set the PRD declares for each
entity. Common-fields resources (PRD §2.6) carry id + created_at +
updated_at + version. Append-only / leaf records (PRD §2.6 / §2.8)
carry only id + created_at — `Contribution`, `Form3922`. `SystemClock`
is a singleton with no id, updated_at, or version.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Status enum-like sets — used by entity assertions.
# ---------------------------------------------------------------------------
PLAN_STATUSES = {"DRAFT", "ACTIVE", "TERMINATED"}
OFFERING_PERIOD_STATUSES = {"OPEN", "CLOSED", "PURCHASED"}
ENROLLMENT_STATUSES = {"ACTIVE", "WITHDRAWN", "COMPLETED"}
CONTRIBUTION_STATUSES = {"POSTED", "REFUNDED", "CONSUMED"}
HOLDING_PERIOD_STATUSES = {
    "WITHIN_BOTH", "PAST_ONE_YEAR_FROM_PURCHASE", "QUALIFYING_MATURE",
}
PURCHASE_DISPOSITION_STATUSES = {
    "HELD", "DISPOSED_QUALIFYING", "DISPOSED_DISQUALIFYING",
}
DISPOSITION_STATUSES = {"REPORTED", "AMENDED", "VOIDED"}
DISPOSITION_CLASSIFICATIONS = {"QUALIFYING", "DISQUALIFYING"}


# ---------------------------------------------------------------------------
# Envelope checks — common-fields vs append-only / leaf.
# ---------------------------------------------------------------------------
def assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.6: "id is a server-minted UUID string ... `created_at` is
    an ISO 8601 UTC timestamp ... `updated_at` is an ISO 8601 UTC
    timestamp ... `version` is an integer that starts at the resource's
    initial creation value and is incremented by one on every mutation."
    """
    assert "id" in data, "common-fields row missing 'id'"
    assert is_valid_uuid(str(data["id"])), (
        f"id must be a UUID without prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing 'created_at'"
    assert is_iso8601_timestamp(str(data["created_at"])), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )
    assert "updated_at" in data, "missing 'updated_at'"
    assert is_iso8601_timestamp(str(data["updated_at"])), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing 'version'"
    assert isinstance(data["version"], int), (
        f"version must be int, got {type(data['version'])}"
    )
    assert data["version"] >= 1, (
        f"version must be >= 1, got {data['version']}"
    )


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """PRD §2.6: "A `Contribution` carries only `id` and `created_at` —
    both `updated_at` and `version` are absent on contribution rows ...
    A `Form3922` likewise carries only `id` and `created_at`."
    """
    assert "id" in data, "append-only row missing 'id'"
    assert is_valid_uuid(str(data["id"])), (
        f"id must be a UUID, got {data['id']!r}"
    )
    assert "created_at" in data, "missing 'created_at'"
    assert is_iso8601_timestamp(str(data["created_at"])), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )
    assert "updated_at" not in data, (
        "append-only entity must not expose 'updated_at' "
        f"(found {data.get('updated_at')!r})"
    )
    assert "version" not in data, (
        "append-only entity must not expose 'version' "
        f"(found {data.get('version')!r})"
    )


def assert_status(data: Dict[str, Any], expected: str,
                  field: str = "status") -> None:
    actual = data.get(field)
    assert actual == expected, (
        f"Expected {field}={expected!r}, got {actual!r}"
    )


def assert_version_incremented_by(prior: Dict[str, Any],
                                  current: Dict[str, Any],
                                  delta: int = 1) -> None:
    """PRD §2.10: "Every successful mutation refreshes `updated_at` and
    increments `version` by one."
    """
    assert "version" in prior and "version" in current, (
        "both prior and current must carry version"
    )
    assert current["version"] == prior["version"] + delta, (
        f"Expected version {prior['version']} + {delta} = "
        f"{prior['version'] + delta}, got {current['version']}"
    )


# ---------------------------------------------------------------------------
# Plan — PRD §3.1
# ---------------------------------------------------------------------------
def assert_plan(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("name"), str) and 1 <= len(data["name"]) <= 120
    assert data.get("status") in PLAN_STATUSES, (
        f"Plan.status must be one of {PLAN_STATUSES}, got {data.get('status')!r}"
    )
    assert isinstance(data.get("offering_period_months"), int)
    assert 6 <= data["offering_period_months"] <= 24, (
        f"offering_period_months out of [6,24]: {data['offering_period_months']}"
    )
    assert isinstance(data.get("max_contribution_rate_bp"), int)
    assert 0 < data["max_contribution_rate_bp"] <= 1500
    assert isinstance(data.get("annual_accrual_cap_cents"), int)
    assert data["annual_accrual_cap_cents"] > 0
    assert isinstance(data.get("lookback_enabled"), bool)
    assert isinstance(data.get("discount_bp"), int)
    assert 0 <= data["discount_bp"] <= 1500
    assert is_iso8601_timestamp(str(data.get("effective_date", "")))


# ---------------------------------------------------------------------------
# OfferingPeriod — PRD §3.2
# ---------------------------------------------------------------------------
def assert_offering_period(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(str(data.get("plan_id", "")))
    assert isinstance(data.get("sequence_number"), int)
    assert data["sequence_number"] >= 1
    assert is_iso8601_timestamp(str(data.get("start_date", "")))
    assert is_iso8601_timestamp(str(data.get("end_date", "")))
    # grant_date_fmv_cents may be null until recorded; once set, > 0.
    g = data.get("grant_date_fmv_cents")
    if g is not None:
        assert isinstance(g, int) and g > 0
    # purchase_date_fmv_cents may be null until PATCH; once set, > 0.
    p = data.get("purchase_date_fmv_cents")
    if p is not None:
        assert isinstance(p, int) and p > 0
    assert data.get("status") in OFFERING_PERIOD_STATUSES, (
        f"OfferingPeriod.status must be one of {OFFERING_PERIOD_STATUSES}, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# Enrollment — PRD §3.3
# ---------------------------------------------------------------------------
def assert_enrollment(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(str(data.get("offering_period_id", "")))
    assert isinstance(data.get("participant_id"), str) \
        and len(data["participant_id"]) > 0
    assert isinstance(data.get("contribution_rate_bp"), int)
    assert 0 < data["contribution_rate_bp"] <= 1500
    assert data.get("status") in ENROLLMENT_STATUSES, (
        f"Enrollment.status must be one of {ENROLLMENT_STATUSES}, "
        f"got {data.get('status')!r}"
    )
    assert isinstance(data.get("ytd_accrual_cents"), int)
    assert data["ytd_accrual_cents"] >= 0


# ---------------------------------------------------------------------------
# Contribution — PRD §3.4 (append-only per §2.6)
# ---------------------------------------------------------------------------
def assert_contribution(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(str(data.get("enrollment_id", "")))
    assert is_iso8601_timestamp(str(data.get("pay_period_end", "")))
    assert isinstance(data.get("gross_pay_cents"), int)
    assert data["gross_pay_cents"] >= 0
    assert isinstance(data.get("amount_cents"), int)
    assert data["amount_cents"] >= 0
    assert data.get("status") in CONTRIBUTION_STATUSES, (
        f"Contribution.status must be one of {CONTRIBUTION_STATUSES}, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# Purchase — PRD §3.5, §3.6
# ---------------------------------------------------------------------------
def assert_purchase(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(str(data.get("plan_id", "")))
    assert is_valid_uuid(str(data.get("offering_period_id", "")))
    assert is_valid_uuid(str(data.get("enrollment_id", "")))
    assert isinstance(data.get("participant_id"), str) \
        and len(data["participant_id"]) > 0
    assert is_iso8601_timestamp(str(data.get("purchase_date", "")))
    for k in ("contributions_used_cents", "chosen_fmv_cents",
              "purchase_price_cents", "shares_purchased", "refund_cents"):
        assert isinstance(data.get(k), int), (
            f"Purchase.{k} must be int, got {data.get(k)!r}"
        )
        assert data[k] >= 0, f"Purchase.{k} must be >= 0, got {data[k]}"
    assert data.get("holding_period_status") in HOLDING_PERIOD_STATUSES, (
        f"Purchase.holding_period_status must be one of "
        f"{HOLDING_PERIOD_STATUSES}, got {data.get('holding_period_status')!r}"
    )
    assert data.get("disposition_status") in PURCHASE_DISPOSITION_STATUSES, (
        f"Purchase.disposition_status must be one of "
        f"{PURCHASE_DISPOSITION_STATUSES}, "
        f"got {data.get('disposition_status')!r}"
    )


def assert_purchase_invariants(data: Dict[str, Any]) -> None:
    """Algebraic invariants from PRD §3.5: floor + refund identity."""
    cu = data["contributions_used_cents"]
    pp = data["purchase_price_cents"]
    s = data["shares_purchased"]
    r = data["refund_cents"]
    assert pp > 0, "purchase_price_cents must be > 0 for a valid purchase"
    assert cu == s * pp + r, (
        f"floor invariant broken: contributions_used={cu} != "
        f"shares*price + refund = {s}*{pp} + {r} = {s * pp + r}"
    )
    assert 0 <= r < pp, (
        f"refund must satisfy 0 <= refund < purchase_price; got {r} vs {pp}"
    )


# ---------------------------------------------------------------------------
# Form3922 — PRD §2.8 (append-only)
# ---------------------------------------------------------------------------
def assert_form_3922(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(str(data.get("purchase_id", "")))
    assert isinstance(data.get("participant_id"), str) \
        and len(data["participant_id"]) > 0
    assert is_iso8601_timestamp(str(data.get("grant_date", "")))
    assert is_iso8601_timestamp(str(data.get("purchase_date", "")))
    for k in (
        "fmv_grant_date_cents", "fmv_purchase_date_cents",
        "exercise_price_per_share_cents", "shares_transferred",
    ):
        assert isinstance(data.get(k), int) and data[k] >= 0, (
            f"Form3922.{k} must be non-negative int"
        )
    assert is_iso8601_timestamp(str(data.get("legal_title_date", "")))
    assert is_iso8601_timestamp(str(data.get("issuance_timestamp", "")))


# ---------------------------------------------------------------------------
# Disposition — PRD §3.7
# ---------------------------------------------------------------------------
def assert_disposition(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(str(data.get("purchase_id", "")))
    assert isinstance(data.get("participant_id"), str) \
        and len(data["participant_id"]) > 0
    assert is_iso8601_timestamp(str(data.get("disposition_date", "")))
    assert isinstance(data.get("shares_disposed"), int)
    assert data["shares_disposed"] >= 0
    assert isinstance(data.get("sale_price_per_share_cents"), int)
    assert data["sale_price_per_share_cents"] > 0
    assert data.get("classification") in DISPOSITION_CLASSIFICATIONS, (
        f"Disposition.classification must be one of "
        f"{DISPOSITION_CLASSIFICATIONS}, got {data.get('classification')!r}"
    )
    assert isinstance(data.get("ordinary_income_cents"), int)
    assert data["ordinary_income_cents"] >= 0
    assert isinstance(data.get("capital_gain_cents"), int)
    # capital_gain may be negative for losses; do NOT assert sign.
    assert data.get("status") in DISPOSITION_STATUSES, (
        f"Disposition.status must be one of {DISPOSITION_STATUSES}, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# SystemClock — PRD §2.9
# ---------------------------------------------------------------------------
def assert_system_clock(data: Dict[str, Any]) -> None:
    assert "current_time" in data, "SystemClock missing 'current_time'"
    assert is_iso8601_timestamp(str(data["current_time"]))
    # last_sweep_at may be null before the first sweep.
    last = data.get("last_sweep_at")
    if last is not None:
        assert is_iso8601_timestamp(str(last))
    # PRD §2.6: SystemClock has no id, updated_at, or version.
    assert "id" not in data, "SystemClock must not expose 'id'"
    assert "updated_at" not in data, "SystemClock must not expose 'updated_at'"
    assert "version" not in data, "SystemClock must not expose 'version'"


__all__ = [
    # Enum-like sets
    "PLAN_STATUSES",
    "OFFERING_PERIOD_STATUSES",
    "ENROLLMENT_STATUSES",
    "CONTRIBUTION_STATUSES",
    "HOLDING_PERIOD_STATUSES",
    "PURCHASE_DISPOSITION_STATUSES",
    "DISPOSITION_STATUSES",
    "DISPOSITION_CLASSIFICATIONS",
    # Envelope checks
    "assert_common_fields",
    "assert_append_only_fields",
    "assert_status",
    "assert_version_incremented_by",
    # Entity assertions
    "assert_plan",
    "assert_offering_period",
    "assert_enrollment",
    "assert_contribution",
    "assert_purchase",
    "assert_purchase_invariants",
    "assert_form_3922",
    "assert_disposition",
    "assert_system_clock",
]
