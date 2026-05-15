"""Entity assertions and domain invariant checkers.

Each `assert_<entity>` validates the structural envelope of an entity
returned by the API: required fields, types, and PRD-enumerated states.

Per PRD §2.4: Advertiser, AccountUser, Campaign, AdGroup, Creative
carry id/created_at/updated_at/version. QualificationDoc, AuctionEvent,
BillingEvent, ConversionEvent, WalletTransaction, ReviewDecision,
AuditLog are append-only and carry only id and created_at — they MUST
NOT carry updated_at or version.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Lookup helpers — fish a specific row out of a list of dicts.
# ---------------------------------------------------------------------------
def find_row(rows: List[Dict[str, Any]], **predicates: Any) -> Dict[str, Any]:
    for row in rows:
        if all(row.get(k) == v for k, v in predicates.items()):
            return row
    raise AssertionError(
        f"No row matching {predicates}. Saw: "
        f"{[dict((k, r.get(k)) for k in predicates) for r in rows]}"
    )


def select_rows(rows: List[Dict[str, Any]],
                **predicates: Any) -> List[Dict[str, Any]]:
    return [
        r for r in rows
        if all(r.get(k) == v for k, v in predicates.items())
    ]


def count_rows(rows: List[Dict[str, Any]], **predicates: Any) -> int:
    return len(select_rows(rows, **predicates))


# ---------------------------------------------------------------------------
# Common-fields helpers — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_common_fields(data: Dict[str, Any]) -> None:
    """Entities that carry id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    version = data.get("version")
    assert isinstance(version, int) and version >= 1, (
        f"version must be a positive integer, got {version!r}"
    )


def _assert_append_only_fields(data: Dict[str, Any]) -> None:
    """Append-only entities — id and created_at only.

    Per PRD §2.4 these entities (QualificationDoc, AuctionEvent,
    BillingEvent, ConversionEvent, WalletTransaction, ReviewDecision,
    AuditLog) MUST NOT expose updated_at or version.
    """
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


def assert_iso_timestamp_with_three_millis(ts: str) -> None:
    """PRD §2.4 — three fractional digits and a trailing 'Z'."""
    assert is_iso8601_timestamp(ts), f"Not ISO 8601: {ts!r}"
    # Require 'YYYY-MM-DDTHH:MM:SS.sssZ' shape with exactly three millis.
    assert "." in ts and ts.endswith("Z"), (
        f"timestamp must end with 'Z' and carry fractional seconds: {ts!r}"
    )
    frac = ts.rsplit(".", 1)[1].rstrip("Z")
    assert len(frac) == 3, (
        f"PRD §2.4 requires three fractional digits, got {frac!r}"
    )


# ===========================================================================
# Advertiser (PRD §2.5, §3.1)
# ===========================================================================
def assert_advertiser(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert data["account_type"] in {"MCC", "SUB_ACCOUNT", "INDEPENDENT"}, (
        f"account_type unexpected: {data.get('account_type')!r}"
    )
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["business_license_number"], str)
    assert data["industry_category"] in {
        "GENERAL", "MEDICAL", "FINANCIAL", "EDUCATION",
    }, f"industry_category unexpected: {data.get('industry_category')!r}"
    assert data["billing_mode"] in {"PREPAY", "POSTPAY"}, (
        f"billing_mode unexpected: {data.get('billing_mode')!r}"
    )
    assert data["status"] in {"PENDING", "ACTIVE", "SUSPENDED", "CLOSED"}, (
        f"status unexpected: {data.get('status')!r}"
    )
    assert data["qualification_status"] in {
        "UNVERIFIED", "UNDER_REVIEW", "VERIFIED", "REJECTED",
    }, (
        f"qualification_status unexpected: "
        f"{data.get('qualification_status')!r}"
    )
    assert data["balance_state"] in {"HEALTHY", "LOW_BALANCE", "ZERO_BALANCE"}
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["consumed_cents"], int)
    assert data["consumed_cents"] >= 0, (
        f"consumed_cents must be non-negative, got {data['consumed_cents']}"
    )
    assert isinstance(data["credit_line_cents"], int)
    assert isinstance(data["low_balance_threshold_cents"], int)
    assert isinstance(data["tax_rate_bps"], int)


# ===========================================================================
# QualificationDoc (PRD §2.5, §3.1)
# ===========================================================================
def assert_qualification_doc(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    # MUST NOT carry updated_at or version per PRD §2.4.
    assert "updated_at" not in data, (
        "QualificationDoc is append-only per PRD §2.4; updated_at must "
        "not be in the response"
    )
    assert "version" not in data, (
        "QualificationDoc is append-only per PRD §2.4; version must "
        "not be in the response"
    )
    assert data["doc_type"] in {
        "BUSINESS_LICENSE", "MEDICAL_PERMIT",
        "FINANCIAL_LICENSE", "EDUCATION_PERMIT",
    }
    assert data["review_status"] in {"PENDING", "APPROVED", "REJECTED"}


# ===========================================================================
# AccountUser (PRD §2.5, §3.2)
# ===========================================================================
def assert_account_user(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["external_user_id"], str) and data["external_user_id"]
    assert data["account_role"] in {
        "OWNER", "CAMPAIGN_MANAGER", "FINANCE", "VIEWER",
    }
    assert data["status"] in {"ACTIVE", "DISABLED"}


# ===========================================================================
# Campaign (PRD §2.5, §3.3)
# ===========================================================================
def assert_campaign(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["daily_budget_cents"], int)
    assert data["daily_budget_cents"] >= 100, (
        f"daily_budget_cents must be >= 100 per PRD §3.3, got "
        f"{data['daily_budget_cents']}"
    )
    assert data["pacing_strategy"] in {"STANDARD", "ACCELERATED"}
    assert data["status"] in {
        "DRAFT", "ACTIVE", "PAUSED", "BUDGET_EXHAUSTED", "ENDED",
    }
    assert isinstance(data["lifetime_spent_cents"], int)
    assert isinstance(data["today_spent_cents"], int)
    assert data["lifetime_spent_cents"] >= 0
    assert data["today_spent_cents"] >= 0


# ===========================================================================
# AdGroup (PRD §2.5, §3.3)
# ===========================================================================
def assert_ad_group(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["bidding_strategy"] in {"CPC", "CPM", "CPA", "OCPX"}
    assert isinstance(data["bid_cents"], int)
    assert isinstance(data["targeting_geo"], list)
    assert data["status"] in {
        "DRAFT", "READY", "RUNNING", "PAUSED",
        "DISAPPROVED", "BUDGET_EXHAUSTED", "ARCHIVED",
    }
    # PRD §3.5: quality_score in [1.0, 10.0]; predicted_ctr in [0.0, 1.0]
    q = data["quality_score"]
    assert isinstance(q, (int, float)) and 1.0 <= q <= 10.0, (
        f"quality_score must be in [1.0, 10.0], got {q!r}"
    )
    p = data["predicted_ctr"]
    assert isinstance(p, (int, float)) and 0.0 <= p <= 1.0, (
        f"predicted_ctr must be in [0.0, 1.0], got {p!r}"
    )
    assert isinstance(data["approved_creative_count"], int)
    assert data["approved_creative_count"] >= 0


# ===========================================================================
# Creative (PRD §2.5, §3.4)
# ===========================================================================
def assert_creative(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert data["format"] in {"IMAGE", "VIDEO", "NATIVE", "HTML5"}
    assert isinstance(data["asset_url"], str) and data["asset_url"]
    assert isinstance(data["headline"], str)
    assert isinstance(data["body_text"], str)
    assert isinstance(data["landing_url"], str)
    assert data["review_status"] in {
        "PENDING_PRESCREEN", "PRESCREEN_FAILED",
        "PENDING_HUMAN_REVIEW", "APPROVED", "REJECTED",
        "APPEAL_FILED", "UNDER_APPEAL_REVIEW", "ARCHIVED",
    }
    assert isinstance(data["version_number"], int) and data["version_number"] >= 1
    assert isinstance(data["appeal_count"], int) and 0 <= data["appeal_count"] <= 1
    assert isinstance(data["rejection_codes"], list)


# ===========================================================================
# AuctionEvent (PRD §2.5, §3.5)
# ===========================================================================
def assert_auction_event(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert "updated_at" not in data, (
        "AuctionEvent is append-only per PRD §2.4"
    )
    assert "version" not in data, (
        "AuctionEvent is append-only per PRD §2.4"
    )
    assert data["exchange"] in {"INTERNAL", "EXTERNAL_RTB"}
    assert data["pricing_rule"] in {"GSP", "VCG"}
    assert isinstance(data["floor_price_cents"], int)
    assert data["device"] in {"DESKTOP", "MOBILE", "TABLET", "CTV"}
    assert isinstance(data["candidate_ad_group_ids"], list)
    assert isinstance(data["filtered_ad_group_ids"], list)
    assert data["outcome"] in {
        "FILLED", "NO_BID", "FLOOR_NOT_MET", "ALL_FILTERED",
    }
    assert isinstance(data["clearing_price_cents"], int)
    assert isinstance(data["bid_shaded"], bool)


# ===========================================================================
# BillingEvent (PRD §2.5, §3.6)
# ===========================================================================
def assert_billing_event(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert "updated_at" not in data, (
        "BillingEvent is append-only per PRD §2.4"
    )
    assert "version" not in data, (
        "BillingEvent is append-only per PRD §2.4"
    )
    assert data["event_type"] in {"IMPRESSION", "CLICK", "CONVERSION"}
    assert data["status"] in {
        "PENDING_IVT", "VALID", "INVALID_TRAFFIC",
        "DEDUPLICATED", "FINALIZED", "REVERSED",
    }
    assert isinstance(data["gross_cost_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["cost_cents"], int)
    # PRD §3.6: cost_cents = gross_cost_cents + tax_cents
    assert data["cost_cents"] == data["gross_cost_cents"] + data["tax_cents"], (
        f"cost_cents must equal gross + tax per PRD §3.6: gross="
        f"{data['gross_cost_cents']}, tax={data['tax_cents']}, "
        f"cost={data['cost_cents']}"
    )


# ===========================================================================
# ConversionEvent (PRD §2.5, §3.7)
# ===========================================================================
def assert_conversion_event(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert "updated_at" not in data, (
        "ConversionEvent is append-only per PRD §2.4"
    )
    assert "version" not in data, (
        "ConversionEvent is append-only per PRD §2.4"
    )
    assert data["source"] in {
        "WEB_PIXEL", "APP_SDK", "S2S", "OFFLINE_UPLOAD",
    }
    assert data["attribution_status"] in {
        "PENDING", "ATTRIBUTED", "UNATTRIBUTED",
    }
    assert data["attribution_model"] in {
        "LAST_CLICK", "POSITION_BASED", "DATA_DRIVEN",
    }
    assert isinstance(data["attribution_window_days"], int)
    assert 1 <= data["attribution_window_days"] <= 90
    assert isinstance(data["value_cents"], int)
    assert isinstance(data["attributed_touchpoints"], list)


# ===========================================================================
# WalletTransaction (PRD §2.5, §3.8)
# ===========================================================================
def assert_wallet_transaction(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert "updated_at" not in data, (
        "WalletTransaction is append-only per PRD §2.4"
    )
    assert "version" not in data, (
        "WalletTransaction is append-only per PRD §2.4"
    )
    assert data["tx_type"] in {
        "RECHARGE", "REFUND", "ADJUSTMENT",
        "INVOICE_SETTLEMENT", "CONSUMPTION",
    }
    assert data["status"] in {"PENDING", "SETTLED", "FAILED", "REVERSED"}
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["idempotency_key"], str) and data["idempotency_key"]


# ===========================================================================
# ReviewDecision (PRD §2.5, §3.4)
# ===========================================================================
def assert_review_decision(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert "updated_at" not in data, (
        "ReviewDecision is append-only per PRD §2.4"
    )
    assert "version" not in data, (
        "ReviewDecision is append-only per PRD §2.4"
    )
    assert data["decision_type"] in {
        "PRESCREEN", "HUMAN_REVIEW", "APPEAL_DECISION",
    }
    assert data["outcome"] in {"APPROVE", "REJECT"}
    assert isinstance(data["reviewer_user_id"], str) and data["reviewer_user_id"]


# ===========================================================================
# AuditLog (PRD §2.5)
# ===========================================================================
def assert_audit_log(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert "updated_at" not in data, (
        "AuditLog is append-only per PRD §2.4"
    )
    assert "version" not in data, (
        "AuditLog is append-only per PRD §2.4"
    )
    assert data["action"] in {
        "REVIEW_DECISION", "BALANCE_ADJUSTMENT",
        "REFUND", "CREDIT_LINE_CHANGE", "ACCOUNT_STATUS_CHANGE",
    }
    assert isinstance(data["actor_user_id"], str)
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["target_entity_type"], str)
    assert isinstance(data["target_entity_id"], str)


# ===========================================================================
# Domain invariants
# ===========================================================================
def assert_version_incremented_by_one(before: Dict[str, Any],
                                      after: Dict[str, Any]) -> None:
    """PRD §2.4: every mutation increments the directly-mutated
    resource's version by 1.
    """
    assert before["version"] + 1 == after["version"], (
        f"PRD §2.4: version must increment by exactly 1 on every "
        f"mutation; before={before['version']}, after={after['version']}"
    )


def assert_balance_state_consistent(advertiser: Dict[str, Any]) -> None:
    """PRD §3.9: balance_state derives from balance_cents and
    low_balance_threshold_cents.

    balance_cents <= 0                                  -> ZERO_BALANCE
    0 < balance_cents <= low_balance_threshold_cents    -> LOW_BALANCE
    balance_cents > low_balance_threshold_cents         -> HEALTHY
    """
    b = advertiser["balance_cents"]
    t = advertiser["low_balance_threshold_cents"]
    expected = (
        "ZERO_BALANCE" if b <= 0
        else "LOW_BALANCE" if b <= t
        else "HEALTHY"
    )
    assert advertiser["balance_state"] == expected, (
        f"PRD §3.9 derivation: balance_cents={b}, threshold={t} should "
        f"yield {expected}, got {advertiser['balance_state']!r}"
    )


def assert_billing_cost_formula(event: Dict[str, Any],
                                tax_rate_bps: int) -> None:
    """PRD §3.6: tax_cents = floor(gross_cost_cents * tax_rate_bps /
    10000); cost_cents = gross_cost_cents + tax_cents. ROUNDING ORDER
    FIXED: compute tax on gross then add.
    """
    gross = event["gross_cost_cents"]
    expected_tax = (gross * tax_rate_bps) // 10000
    expected_cost = gross + expected_tax
    assert event["tax_cents"] == expected_tax, (
        f"PRD §3.6 tax formula: floor({gross} * {tax_rate_bps} / 10000)"
        f" = {expected_tax}, got {event['tax_cents']}"
    )
    assert event["cost_cents"] == expected_cost, (
        f"PRD §3.6 cost = gross + tax: {expected_cost}, got "
        f"{event['cost_cents']}"
    )


def assert_attributed_credit_sums_to_value(conv: Dict[str, Any]) -> None:
    """PRD §3.7: rounding remainder goes to the LAST touchpoint, so the
    sum of credit_cents must equal conversion.value_cents.
    """
    tps = conv["attributed_touchpoints"]
    if not tps:
        return
    s = sum(t["credit_cents"] for t in tps)
    assert s == conv["value_cents"], (
        f"PRD §3.7 credit_cents must sum to value_cents="
        f"{conv['value_cents']}, got {s}"
    )


def assert_cash_flow_conserved(balance_before: int,
                               balance_after: int) -> None:
    """PRD §2.9, §3.6, §3.8: a forward CONSUMPTION + its reversing
    REFUND, or a forward WalletTransaction + its reversal, must produce
    a net change of zero to balance_cents.
    """
    assert balance_before == balance_after, (
        f"PRD §2.9 net-zero invariant: balance_cents must be unchanged "
        f"after a forward+reverse pair; before={balance_before}, "
        f"after={balance_after}"
    )


__all__ = [
    "find_row",
    "select_rows",
    "count_rows",
    "assert_iso_timestamp_with_three_millis",
    "assert_advertiser",
    "assert_qualification_doc",
    "assert_account_user",
    "assert_campaign",
    "assert_ad_group",
    "assert_creative",
    "assert_auction_event",
    "assert_billing_event",
    "assert_conversion_event",
    "assert_wallet_transaction",
    "assert_review_decision",
    "assert_audit_log",
    "assert_version_incremented_by_one",
    "assert_balance_state_consistent",
    "assert_billing_cost_formula",
    "assert_attributed_credit_sums_to_value",
    "assert_cash_flow_conserved",
]
