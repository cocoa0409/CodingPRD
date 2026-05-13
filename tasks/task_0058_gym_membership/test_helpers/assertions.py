"""Per-entity assertions for the Gym Membership API.

PRD §2.4 splits entities into two field-shapes:
- Versioned (id + created_at + updated_at + version): Member, CardType,
  Card, Trainer, TrainerSlot, PTBooking, PTPackage, GroupClass,
  GroupBooking, FreezeEpisode.
- Append-only (id + created_at only; no updated_at, no version):
  WalletTransaction, TransferRecord, CommissionRecord, PayoutCycle,
  RenewalReminder, AuditLogEntry.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Shared shape checkers
# ---------------------------------------------------------------------------
def _check_versioned_fields(data: Dict[str, Any], entity: str) -> None:
    """PRD §2.4 versioned shape: id, created_at, updated_at, version."""
    assert "id" in data, f"{entity} missing id"
    assert is_valid_uuid(data["id"]), (
        f"{entity}.id must be UUID, got {data['id']!r}"
    )
    assert "created_at" in data and is_iso8601_timestamp(
        data["created_at"]
    ), f"{entity}.created_at must be ISO 8601 UTC"
    assert "updated_at" in data and is_iso8601_timestamp(
        data["updated_at"]
    ), f"{entity}.updated_at must be ISO 8601 UTC"
    assert "version" in data, f"{entity} missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"{entity}.version must be >= 1, got {data.get('version')!r}"
    )


def _check_append_only_fields(data: Dict[str, Any], entity: str) -> None:
    """PRD §2.4 append-only shape: id + created_at ONLY."""
    assert "id" in data, f"{entity} missing id"
    assert is_valid_uuid(data["id"]), (
        f"{entity}.id must be UUID, got {data['id']!r}"
    )
    assert "created_at" in data and is_iso8601_timestamp(
        data["created_at"]
    ), f"{entity}.created_at must be ISO 8601 UTC"


# ---------------------------------------------------------------------------
# Allowed enum sets (mirroring PRD prose)
# ---------------------------------------------------------------------------
CARD_TYPE_STATES = {"ACTIVE", "RETIRED"}
CARD_CATEGORIES = {"PER_VISIT", "MONTHLY", "ANNUAL"}
CARD_STATES = {"PENDING", "ACTIVE", "FROZEN", "EXPIRED",
               "REFUNDED", "TRANSFERRED"}
FREEZE_EPISODE_STATES = {"REQUESTED", "APPROVED", "SETTLED",
                         "REJECTED", "CANCELED"}
FREEZE_REASONS = {"ILLNESS", "BUSINESS_TRIP"}
TRAINER_STATES = {"ACTIVE", "INACTIVE"}
TRAINER_TIERS = {"BRONZE", "SILVER", "GOLD"}
TRAINER_SLOT_STATES = {"OPEN", "RESERVED", "COMPLETED", "CANCELED", "NO_SHOW"}
PT_BOOKING_STATES = {"CONFIRMED", "COMPLETED", "CANCELED", "NO_SHOW"}
PT_BOOKING_MODES = {"SINGLE", "PACKAGE"}
PT_PACKAGE_STATES = {"ACTIVE", "EXHAUSTED", "REFUNDED"}
GROUP_CLASS_STATES = {"SCHEDULED", "CANCELED", "COMPLETED"}
GROUP_BOOKING_STATES = {"CONFIRMED", "WAITLISTED", "CANCELED",
                        "ATTENDED", "NO_SHOW"}
WALLET_TXN_KINDS = {"RECHARGE", "BONUS_GRANT", "DEBIT", "REFUND",
                    "BONUS_EXPIRE", "ADJUSTMENT"}
WALLET_BUCKETS = {"PRINCIPAL", "BONUS"}
WALLET_SERVICE_TYPES = {"PT_SESSION", "GROUP_CLASS", "CARD_ISSUANCE",
                        "TRANSFER_FEE"}
COMMISSION_KINDS = {"SESSION", "PACKAGE_SALE", "TIER_BONUS", "REVERSAL"}
PAYOUT_CYCLE_STATES = {"OPEN", "CLOSED"}
REMINDER_TIERS = {"T30", "T7", "T0"}
REMINDER_STATES = {"SENT", "AUTO_RENEW_TRIGGERED", "LAPSED"}
AUDIT_ACTIONS = {"CARD_ADJUST", "COMMISSION_ADJUST", "CARD_REFUND",
                 "FREEZE_OVERRIDE", "COMMISSION_REVERSAL"}
NOTIFICATION_CHANNELS = {"SMS", "EMAIL", "IM", "PUSH"}


# ===========================================================================
# Versioned entities
# ===========================================================================
def assert_member(data: Dict[str, Any]) -> None:
    """PRD §3.1 Member fields."""
    _check_versioned_fields(data, "Member")
    assert isinstance(data.get("full_name"), str) and len(data["full_name"]) >= 1
    assert isinstance(data.get("phone"), str)
    assert isinstance(data.get("email"), str)
    # family_group_id is optional
    if "family_group_id" in data and data["family_group_id"] is not None:
        assert isinstance(data["family_group_id"], str)
    if "notification_channels" in data and data["notification_channels"] is not None:
        assert isinstance(data["notification_channels"], list)
        for ch in data["notification_channels"]:
            assert ch in NOTIFICATION_CHANNELS, (
                f"unknown notification channel {ch!r}"
            )
    if "auto_renew_authorized" in data:
        assert isinstance(data["auto_renew_authorized"], bool)
    # Wallet-balance computed fields (PRD §3.1)
    if "wallet_balance_cents" in data:
        assert isinstance(data["wallet_balance_cents"], int)
    if "bonus_balance_cents" in data:
        assert isinstance(data["bonus_balance_cents"], int)


def assert_card_type(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "CardType")
    assert isinstance(data.get("code"), str)
    assert data.get("category") in CARD_CATEGORIES
    assert isinstance(data.get("price_cents"), int) and data["price_cents"] >= 0
    assert isinstance(data.get("validity_days"), int)
    assert isinstance(data.get("visit_quota"), int) and data["visit_quota"] >= 0
    assert isinstance(data.get("family_shareable"), bool)
    assert isinstance(data.get("max_freeze_days"), int) and data["max_freeze_days"] >= 0
    tfb = data.get("transfer_fee_pct_bp")
    assert isinstance(tfb, int) and 0 <= tfb <= 10_000
    rdb = data.get("renewal_discount_pct_bp")
    assert isinstance(rdb, int) and 0 <= rdb <= 10_000
    assert isinstance(data.get("refund_eligibility_days"), int)
    assert data.get("status") in CARD_TYPE_STATES


def assert_card(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "Card")
    assert isinstance(data.get("card_type_id"), str)
    assert isinstance(data.get("holder_member_id"), str)
    assert isinstance(data.get("issuance_price_cents"), int)
    assert data.get("status") in CARD_STATES
    if data.get("activation_date") is not None:
        assert is_iso8601_timestamp(data["activation_date"])
    if data.get("original_expiry_date") is not None:
        assert is_iso8601_timestamp(data["original_expiry_date"])
    if data.get("effective_expiry_date") is not None:
        assert is_iso8601_timestamp(data["effective_expiry_date"])
    if "visits_consumed" in data:
        assert isinstance(data["visits_consumed"], int) and data["visits_consumed"] >= 0
    if "cumulative_freeze_days" in data:
        assert isinstance(data["cumulative_freeze_days"], int)


def assert_trainer(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "Trainer")
    assert isinstance(data.get("full_name"), str)
    assert isinstance(data.get("specialties"), list) and len(data["specialties"]) >= 1
    scb = data.get("session_commission_pct_bp")
    assert isinstance(scb, int) and 0 <= scb <= 10_000
    pcb = data.get("package_commission_pct_bp")
    assert isinstance(pcb, int) and 0 <= pcb <= 10_000
    assert data.get("tier") in TRAINER_TIERS
    assert data.get("status") in TRAINER_STATES


def assert_trainer_slot(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "TrainerSlot")
    assert isinstance(data.get("trainer_id"), str)
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))
    assert isinstance(data.get("specialty_code"), str)
    assert data.get("status") in TRAINER_SLOT_STATES


def assert_pt_booking(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "PTBooking")
    assert isinstance(data.get("member_id"), str)
    assert isinstance(data.get("trainer_id"), str)
    assert isinstance(data.get("slot_id"), str)
    assert data.get("billing_mode") in PT_BOOKING_MODES
    assert isinstance(data.get("session_price_cents"), int)
    assert data.get("status") in PT_BOOKING_STATES
    assert is_iso8601_timestamp(data.get("scheduled_starts_at", ""))


def assert_pt_package(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "PTPackage")
    assert isinstance(data.get("member_id"), str)
    assert isinstance(data.get("trainer_id"), str)
    ts = data.get("total_sessions")
    assert isinstance(ts, int) and ts >= 1
    gpc = data.get("gross_price_cents")
    assert isinstance(gpc, int) and gpc >= 0
    sc = data.get("sessions_consumed")
    assert isinstance(sc, int) and sc >= 0
    assert data.get("status") in PT_PACKAGE_STATES


def assert_group_class(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "GroupClass")
    assert isinstance(data.get("class_code"), str)
    assert isinstance(data.get("instructor_trainer_id"), str)
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))
    cap = data.get("capacity")
    assert isinstance(cap, int) and cap >= 1
    assert data.get("status") in GROUP_CLASS_STATES
    if "confirmed_count" in data:
        assert isinstance(data["confirmed_count"], int)
        assert data["confirmed_count"] >= 0
    if "waitlist_count" in data:
        assert isinstance(data["waitlist_count"], int)
        assert data["waitlist_count"] >= 0


def assert_group_booking(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "GroupBooking")
    assert isinstance(data.get("class_id"), str)
    assert isinstance(data.get("member_id"), str)
    assert data.get("status") in GROUP_BOOKING_STATES
    if data.get("status") == "WAITLISTED":
        # PRD §3.9: "the row carries a 1-based waitlist_position"
        wp = data.get("waitlist_position")
        assert isinstance(wp, int) and wp >= 1, (
            f"WAITLISTED booking must carry 1-based waitlist_position, "
            f"got {wp!r}"
        )


def assert_freeze_episode(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "FreezeEpisode")
    assert isinstance(data.get("card_id"), str)
    assert data.get("reason") in FREEZE_REASONS
    rd = data.get("requested_days")
    assert isinstance(rd, int) and rd >= 1
    assert data.get("status") in FREEZE_EPISODE_STATES


# ===========================================================================
# Append-only entities — id + created_at ONLY, no updated_at, no version.
# ===========================================================================
def assert_wallet_transaction(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "WalletTransaction")
    assert "updated_at" not in data, (
        "WalletTransaction is append-only — must NOT carry updated_at"
    )
    assert "version" not in data, (
        "WalletTransaction is append-only — must NOT carry version"
    )
    assert isinstance(data.get("member_id"), str)
    assert data.get("kind") in WALLET_TXN_KINDS
    assert isinstance(data.get("amount_cents"), int)
    assert data.get("bucket") in WALLET_BUCKETS


def assert_transfer_record(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "TransferRecord")
    assert "updated_at" not in data
    assert "version" not in data
    assert isinstance(data.get("source_card_id"), str)
    assert isinstance(data.get("destination_card_id"), str)
    assert isinstance(data.get("from_member_id"), str)
    assert isinstance(data.get("to_member_id"), str)
    assert isinstance(data.get("remaining_value_cents"), int)
    assert isinstance(data.get("transfer_fee_cents"), int)


def assert_commission_record(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "CommissionRecord")
    assert "updated_at" not in data
    assert "version" not in data
    assert isinstance(data.get("trainer_id"), str)
    assert data.get("kind") in COMMISSION_KINDS
    assert isinstance(data.get("amount_cents"), int)
    assert isinstance(data.get("ref_entity"), str)


def assert_payout_cycle(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "PayoutCycle")
    assert "updated_at" not in data
    assert "version" not in data
    assert is_iso8601_timestamp(data.get("cycle_start", ""))
    assert is_iso8601_timestamp(data.get("cycle_end", ""))
    assert data.get("status") in PAYOUT_CYCLE_STATES


def assert_renewal_reminder(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "RenewalReminder")
    assert "updated_at" not in data
    assert "version" not in data
    assert isinstance(data.get("card_id"), str)
    assert data.get("tier") in REMINDER_TIERS
    assert data.get("status") in REMINDER_STATES
    if "channels_dispatched" in data:
        assert isinstance(data["channels_dispatched"], list)
        for ch in data["channels_dispatched"]:
            assert ch in NOTIFICATION_CHANNELS


def assert_audit_log_entry(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "AuditLogEntry")
    assert "updated_at" not in data
    assert "version" not in data
    assert isinstance(data.get("actor_role"), str)
    assert isinstance(data.get("actor_id"), str)
    assert data.get("action") in AUDIT_ACTIONS
    assert isinstance(data.get("target_entity"), str)


# ===========================================================================
# Helpers for searching ledger / commission / audit rows
# ===========================================================================
def find_wallet_txn(rows: Iterable[Dict[str, Any]], **filters) -> List[Dict[str, Any]]:
    """Return all WalletTransaction rows matching every filter kw."""
    out = []
    for r in rows:
        match = True
        for k, v in filters.items():
            if k == "ref_startswith":
                if not (r.get("ref_entity") or "").startswith(v):
                    match = False
                    break
            else:
                if r.get(k) != v:
                    match = False
                    break
        if match:
            out.append(r)
    return out


def find_commission_rows(
    rows: Iterable[Dict[str, Any]], **filters,
) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        ok = True
        for k, v in filters.items():
            if k == "ref_startswith":
                if not (r.get("ref_entity") or "").startswith(v):
                    ok = False
                    break
            elif k == "ref_equals":
                if r.get("ref_entity") != v:
                    ok = False
                    break
            else:
                if r.get(k) != v:
                    ok = False
                    break
        if ok:
            out.append(r)
    return out


def find_audit_entries(
    rows: Iterable[Dict[str, Any]], **filters,
) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        ok = True
        for k, v in filters.items():
            if k == "target_startswith":
                if not (r.get("target_entity") or "").startswith(v):
                    ok = False
                    break
            else:
                if r.get(k) != v:
                    ok = False
                    break
        if ok:
            out.append(r)
    return out


__all__ = [
    "CARD_TYPE_STATES", "CARD_CATEGORIES", "CARD_STATES",
    "FREEZE_EPISODE_STATES", "FREEZE_REASONS",
    "TRAINER_STATES", "TRAINER_TIERS", "TRAINER_SLOT_STATES",
    "PT_BOOKING_STATES", "PT_BOOKING_MODES", "PT_PACKAGE_STATES",
    "GROUP_CLASS_STATES", "GROUP_BOOKING_STATES",
    "WALLET_TXN_KINDS", "WALLET_BUCKETS", "WALLET_SERVICE_TYPES",
    "COMMISSION_KINDS", "PAYOUT_CYCLE_STATES",
    "REMINDER_TIERS", "REMINDER_STATES", "AUDIT_ACTIONS",
    "NOTIFICATION_CHANNELS",
    "assert_member", "assert_card_type", "assert_card",
    "assert_trainer", "assert_trainer_slot",
    "assert_pt_booking", "assert_pt_package",
    "assert_group_class", "assert_group_booking",
    "assert_freeze_episode",
    "assert_wallet_transaction", "assert_transfer_record",
    "assert_commission_record", "assert_payout_cycle",
    "assert_renewal_reminder", "assert_audit_log_entry",
    "find_wallet_txn", "find_commission_rows", "find_audit_entries",
]
