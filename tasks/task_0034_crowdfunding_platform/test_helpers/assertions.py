"""Per-entity assertions and domain invariant checkers.

Field shape and value-range checks pinned to PRD prose. Each assertion
checks exactly the surface contract the PRD declares.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields helpers (PRD §2.4)
# ---------------------------------------------------------------------------
def _assert_versioned(data: Dict[str, Any], label: str) -> None:
    """Standard resources expose id, created_at, updated_at, version
    (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 with 3 fractional digits, "
        f"got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601 with 3 fractional digits, "
        f"got {data.get('updated_at')!r}"
    )
    version = data.get("version")
    assert isinstance(version, int) and version >= 1, (
        f"{label}.version must be a positive integer, got {version!r}"
    )


def _assert_append_only(data: Dict[str, Any], label: str) -> None:
    """Append-only entries (ProgressUpdate, AuditLogEntry, EscrowLedgerEntry)
    expose only id and created_at per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# Initiator
# ---------------------------------------------------------------------------
def assert_initiator(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Initiator")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["kyc_status"] in {"PENDING", "VERIFIED", "REJECTED"}


# ---------------------------------------------------------------------------
# Backer
# ---------------------------------------------------------------------------
def assert_backer(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Backer")
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------
def assert_project(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Project")
    assert isinstance(data["initiator_id"], str) and data["initiator_id"]
    assert isinstance(data["title"], str) and 4 <= len(data["title"]) <= 120
    assert data["category"] in {"TECH", "ART", "COMMUNITY"}
    assert isinstance(data["description_md"], str)
    assert isinstance(data["media_uris"], list)
    assert isinstance(data["risk_disclosure"], str)
    assert data["funding_model"] in {"ALL_OR_NOTHING", "KEEP_IT_ALL"}
    assert isinstance(data["funding_target_cents"], int)
    assert data["funding_target_cents"] > 0
    assert is_iso8601_timestamp(data["deadline"])
    assert data["status"] in {
        "DRAFT", "CONTENT_REVIEW", "LEGAL_REVIEW", "FINANCIAL_REVIEW",
        "REJECTED", "LIVE", "SUCCEEDED", "FAILED", "CANCELLED",
    }
    # provisional_raised_cents and final_raised_cents are computed integers.
    assert isinstance(data["provisional_raised_cents"], int)
    assert data["provisional_raised_cents"] >= 0
    assert isinstance(data["final_raised_cents"], int)
    assert data["final_raised_cents"] >= 0


# ---------------------------------------------------------------------------
# Reward
# ---------------------------------------------------------------------------
def assert_reward(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Reward")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["tier_label"], str) and data["tier_label"]
    assert isinstance(data["pledge_amount_cents"], int)
    assert data["pledge_amount_cents"] > 0
    assert data["reward_type"] in {"PHYSICAL", "DIGITAL"}
    inv_limit = data.get("inventory_limit")
    assert inv_limit is None or (
        isinstance(inv_limit, int) and inv_limit >= 0
    )
    assert isinstance(data["inventory_claimed"], int)
    assert data["inventory_claimed"] >= 0


# ---------------------------------------------------------------------------
# AddOnItem
# ---------------------------------------------------------------------------
def assert_add_on_item(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "AddOnItem")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["price_cents"], int)
    assert data["price_cents"] > 0
    assert isinstance(data["requires_shipping"], bool)
    inv_limit = data.get("inventory_limit")
    assert inv_limit is None or (
        isinstance(inv_limit, int) and inv_limit >= 0
    )
    assert isinstance(data["inventory_claimed"], int)
    assert data["inventory_claimed"] >= 0


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------
def assert_order(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Order")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["backer_id"], str)
    assert isinstance(data["reward_id"], str)
    assert isinstance(data.get("add_ons", []), list)
    assert isinstance(data["payment_method_token"], str)
    assert isinstance(data["pledge_amount_cents"], int)
    assert data["pledge_amount_cents"] >= 0
    assert isinstance(data["add_ons_total_cents"], int)
    assert data["add_ons_total_cents"] >= 0
    assert isinstance(data["order_total_cents"], int)
    assert data["order_total_cents"] == (
        data["pledge_amount_cents"] + data["add_ons_total_cents"]
    ), (
        "Order.order_total_cents must equal pledge_amount_cents + "
        "add_ons_total_cents (PRD §3.4)"
    )
    assert data["payment_status"] in {
        "AUTHORIZED", "CHARGE_PENDING", "CHARGED", "CHARGE_FAILED",
        "REFUND_PENDING", "REFUNDED", "PARTIALLY_REFUNDED", "VOIDED",
    }
    assert data["fulfillment_status"] in {
        "NOT_STARTED", "PARTIALLY_SHIPPED", "FULLY_SHIPPED",
        "NOT_APPLICABLE",
    }
    assert is_iso8601_timestamp(data["order_modification_locked_at"])
    assert isinstance(data["refundable_remainder_cents"], int)
    assert data["refundable_remainder_cents"] >= 0


# ---------------------------------------------------------------------------
# RefundRequest
# ---------------------------------------------------------------------------
def assert_refund_request(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "RefundRequest")
    assert isinstance(data["order_id"], str)
    assert data["reason"] in {
        "PROJECT_FAILED", "PROJECT_CANCELLED", "DISPUTE", "PLATFORM_MANDATORY"
    }
    assert isinstance(data["requested_amount_cents"], int)
    assert data["requested_amount_cents"] >= 0
    assert data["status"] in {
        "PENDING_REVIEW", "APPROVED", "REJECTED", "EXECUTED", "FAILED"
    }
    assert data["triggered_by"] in {
        "BACKER", "INITIATOR", "PLATFORM_AUTO"
    }


# ---------------------------------------------------------------------------
# SettlementBatch
# ---------------------------------------------------------------------------
def assert_settlement_batch(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "SettlementBatch")
    assert isinstance(data["project_id"], str)
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    for fld in ("gross_charged_cents", "commission_cents", "channel_fee_cents",
                "refund_reversal_cents", "tax_withheld_cents",
                "net_payout_cents"):
        assert isinstance(data[fld], int), (
            f"SettlementBatch.{fld} must be int (cents)"
        )
    assert data["status"] in {"DRAFT", "FINALIZED", "PAID", "FAILED"}


# ---------------------------------------------------------------------------
# ProgressUpdate (append-only)
# ---------------------------------------------------------------------------
def assert_progress_update(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "ProgressUpdate")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["body_md"], str)
    assert data["visibility"] in {"PUBLIC", "BACKERS_ONLY"}


# ---------------------------------------------------------------------------
# AuditLogEntry (append-only)
# ---------------------------------------------------------------------------
def assert_audit_log_entry(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "AuditLogEntry")
    assert data["subject_type"] in {
        "PROJECT", "ORDER", "REFUND_REQUEST", "SETTLEMENT_BATCH",
        "ESCROW_LEDGER",
    }
    assert isinstance(data["subject_id"], str) and data["subject_id"]
    assert data["event_type"] in {
        "STATUS_CHANGE", "FUND_FLOW", "REFUND_EXECUTED", "SETTLEMENT_PAID",
        "REVIEW_DECISION", "EXTERNAL_EVENT_RECEIVED",
    }
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    assert isinstance(data["actor_id"], str) and data["actor_id"]


# ---------------------------------------------------------------------------
# EscrowLedgerEntry (append-only)
# ---------------------------------------------------------------------------
def assert_escrow_ledger_entry(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "EscrowLedgerEntry")
    assert isinstance(data["project_id"], str)
    # PRD §2.10: 'Settlement-payout entries leave order_id null; all other
    # entry types pin both project_id and order_id.'
    if data["entry_type"] == "SETTLEMENT_PAYOUT":
        assert data.get("order_id") in (None, "", )
    else:
        assert isinstance(data.get("order_id"), str) and data["order_id"]
    assert data["entry_type"] in {
        "AUTH_HOLD", "CHARGE_CAPTURE", "CHARGE_VOID", "REFUND_OUT",
        "COMMISSION_HOLD", "COMMISSION_REVERSAL", "CHANNEL_FEE",
        "SETTLEMENT_PAYOUT",
    }
    assert isinstance(data["amount_cents"], int)


# ---------------------------------------------------------------------------
# Iteration helpers — find ledger / audit entries matching a predicate.
# ---------------------------------------------------------------------------
def find_ledger_entries(
    entries: Iterable[Dict[str, Any]],
    *,
    entry_type: Optional[str] = None,
    order_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for e in entries:
        if entry_type is not None and e.get("entry_type") != entry_type:
            continue
        if order_id is not None and e.get("order_id") != order_id:
            continue
        out.append(e)
    return out


def find_audit_entries(
    entries: Iterable[Dict[str, Any]],
    *,
    subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
    event_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for e in entries:
        if subject_type is not None and e.get("subject_type") != subject_type:
            continue
        if subject_id is not None and e.get("subject_id") != subject_id:
            continue
        if event_type is not None and e.get("event_type") != event_type:
            continue
        out.append(e)
    return out


__all__ = [
    "assert_initiator",
    "assert_backer",
    "assert_project",
    "assert_reward",
    "assert_add_on_item",
    "assert_order",
    "assert_refund_request",
    "assert_settlement_batch",
    "assert_progress_update",
    "assert_audit_log_entry",
    "assert_escrow_ledger_entry",
    "find_ledger_entries",
    "find_audit_entries",
]
