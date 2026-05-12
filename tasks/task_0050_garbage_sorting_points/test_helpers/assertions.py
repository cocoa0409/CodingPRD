"""Entity assertions and domain invariant checkers."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Status sets (mirror enums in types.py)
# ---------------------------------------------------------------------------
COMMUNITY_STATUSES = {"ACTIVE", "ARCHIVED"}
HOUSEHOLD_STATUSES = {"ACTIVE", "SUSPENDED", "ARCHIVED"}
IDENTITY_STATUSES = {"PENDING", "VERIFIED", "REJECTED"}
ACCOUNT_STATUSES = {"INACTIVE", "ACTIVE", "RESTRICTED"}
RESIDENT_RELATIONS = {"HEAD", "SPOUSE", "CHILD", "PARENT", "OTHER"}
GARBAGE_CATEGORIES = {"RECYCLABLE", "HAZARDOUS", "KITCHEN", "OTHER"}
SCORING_METHODS = {"MANUAL", "AI", "SCALE"}
POINT_RULE_STATUSES = {"DRAFT", "ACTIVE", "RETIRED"}
DISPOSAL_STATUSES = {"PENDING", "COMMITTED", "CORRECTED", "VOIDED"}
POINTS_TXN_KINDS = {
    "DISPOSAL_CREDIT",
    "REDEMPTION_DEBIT",
    "REDEMPTION_REFUND",
    "VIOLATION_DEBIT",
    "VIOLATION_REVERSAL",
    "MISJUDGMENT_ADJUSTMENT",
}
MALL_ITEM_STATUSES = {"LISTED", "DELISTED"}
MALL_CHANNELS = {"ONLINE", "STATION"}
REDEMPTION_ORDER_STATUSES = {
    "SUBMITTED",
    "CONFIRMED",
    "REJECTED",
    "FULFILLED",
    "DELIVERED",
    "RETURNED",
}
VIOLATION_TYPES = {"MIS_SORTING", "LITTERING", "NO_CLASSIFICATION"}
VIOLATION_STATUSES = {
    "NEW",
    "APPEALED",
    "UNDER_REVIEW",
    "UPHELD",
    "OVERTURNED",
}
RANKING_GRANULARITIES = {"WEEKLY", "MONTHLY", "YEARLY"}
RANKING_DIMENSIONS = {"HOUSEHOLD", "BUILDING", "COMMUNITY"}
RANKING_PERIOD_STATUSES = {"OPEN", "CLOSED", "PUBLISHED"}
AUDIT_ACTIONS = {
    "POINTS_ADJUSTMENT",
    "VIOLATION_RECORDED",
    "VIOLATION_APPEAL_DECISION",
    "RULE_PUBLISHED",
    "RANKING_PUBLISHED",
}
AUDIT_SUBJECT_KINDS = {
    "DISPOSAL",
    "VIOLATION",
    "POINT_RULE",
    "RANKING_PERIOD",
    "HOUSEHOLD",
}


# ---------------------------------------------------------------------------
# Common-field assertions
# ---------------------------------------------------------------------------
def _assert_common_fields(data: Dict[str, Any], entity: str) -> None:
    """For entities with common_fields: id + created_at + updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity}.id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer, got {data.get('version')!r}"
    )


def _assert_append_only_common(data: Dict[str, Any], entity: str) -> None:
    """For append-only entities (PointsTransaction, AuditLog):
    only id + created_at — MUST NOT carry updated_at or version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity}.id must be a valid UUID"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_community(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Community")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 80
    assert isinstance(data["code"], str)
    assert data["code"].startswith("CMTY-")
    assert isinstance(data.get("timezone", ""), str) and data["timezone"]
    assert data["status"] in COMMUNITY_STATUSES


def assert_household(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Household")
    assert is_valid_uuid(data["community_id"])
    assert 1 <= len(data["address"]) <= 200
    assert 1 <= len(data["building_code"]) <= 32
    if data.get("head_resident_id") is not None:
        assert is_valid_uuid(data["head_resident_id"])
    assert isinstance(data["points_balance"], int)
    assert isinstance(data["lifetime_points_earned"], int)
    assert data["lifetime_points_earned"] >= 0
    assert data["status"] in HOUSEHOLD_STATUSES


def assert_resident(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Resident")
    assert is_valid_uuid(data["household_id"])
    assert 1 <= len(data["full_name"]) <= 80
    h = data["id_document_hash"]
    assert isinstance(h, str) and len(h) == 64 and h == h.lower(), (
        f"id_document_hash must be 64 lowercase hex chars, got {h!r}"
    )
    assert data["relation"] in RESIDENT_RELATIONS
    assert data["identity_status"] in IDENTITY_STATUSES
    assert data["account_status"] in ACCOUNT_STATUSES
    assert isinstance(data["consecutive_disposal_days"], int)
    assert data["consecutive_disposal_days"] >= 0


def assert_point_rule(data: Dict[str, Any]) -> None:
    """PointRule is special: PRD §2.4 — it has version with a domain meaning
    (per (community_id, category) generation number) but no updated_at."""
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])
    assert is_valid_uuid(data["community_id"])
    assert data["category"] in GARBAGE_CATEGORIES
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["base_rate_per_kg"], (int, float))
    assert 0 <= float(data["base_rate_per_kg"]) <= 1000
    assert 1 <= data["bonus_consecutive_threshold_days"] <= 365
    assert 1.0 <= float(data["bonus_consecutive_multiplier"]) <= 5.0
    assert 0 <= data["peak_period_start_hour"] <= 23
    assert 0 <= data["peak_period_end_hour"] <= 23
    assert isinstance(data["peak_period_bonus_flat"], int)
    assert isinstance(data["category_bonus_flat"], int)
    assert isinstance(data["daily_cap_points"], int)
    assert data["status"] in POINT_RULE_STATUSES
    if data.get("activated_at") is not None:
        assert is_iso8601_timestamp(data["activated_at"])
    if data.get("retired_at") is not None:
        assert is_iso8601_timestamp(data["retired_at"])


def assert_disposal(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Disposal")
    assert is_valid_uuid(data["household_id"])
    assert is_valid_uuid(data["resident_id"])
    assert is_valid_uuid(data["community_id"])
    assert is_iso8601_timestamp(data["disposal_time"])
    assert 1 <= len(data["location_code"]) <= 32
    assert data["declared_category"] in GARBAGE_CATEGORIES
    assert data["actual_category"] in GARBAGE_CATEGORIES
    assert data["scoring_method"] in SCORING_METHODS
    assert 0.0 <= float(data["accuracy_score"]) <= 1.0
    # weight_kg XOR volume_liters
    has_w = data.get("weight_kg") is not None
    has_v = data.get("volume_liters") is not None
    assert has_w ^ has_v, (
        "exactly one of weight_kg / volume_liters must be set on a "
        "committed disposal"
    )
    assert 1 <= len(data["evidence_uri"]) <= 500
    if data["status"] != "PENDING":
        assert is_valid_uuid(data["applied_rule_id"])
        assert isinstance(data["awarded_points"], int)
        assert isinstance(data["cap_overflow_points"], int)
        assert data["awarded_points"] >= 0
        assert data["cap_overflow_points"] >= 0
    assert data["status"] in DISPOSAL_STATUSES


def assert_points_transaction(data: Dict[str, Any]) -> None:
    _assert_append_only_common(data, "PointsTransaction")
    assert is_valid_uuid(data["household_id"])
    assert data["kind"] in POINTS_TXN_KINDS
    assert isinstance(data["amount"], int)
    assert isinstance(data["balance_after"], int)
    assert data["related_entity_kind"] in {
        "DISPOSAL", "REDEMPTION_ORDER", "VIOLATION",
    }
    assert is_valid_uuid(data["related_entity_id"])


def assert_mall_item(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "MallItem")
    assert is_valid_uuid(data["community_id"])
    assert 1 <= len(data["name"]) <= 120
    assert isinstance(data["cost_points"], int) and data["cost_points"] >= 1
    assert data["cost_points"] <= 1_000_000
    assert isinstance(data["stock"], int) and data["stock"] >= 0
    assert data["channel"] in MALL_CHANNELS
    assert data["status"] in MALL_ITEM_STATUSES


def assert_redemption_order(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "RedemptionOrder")
    assert is_valid_uuid(data["household_id"])
    assert is_valid_uuid(data["resident_id"])
    assert is_valid_uuid(data["mall_item_id"])
    assert 1 <= data["quantity"] <= 50
    assert isinstance(data["unit_cost_points"], int)
    assert isinstance(data["total_cost_points"], int)
    assert data["total_cost_points"] == data["quantity"] * data["unit_cost_points"]
    assert data["channel"] in MALL_CHANNELS
    assert data["status"] in REDEMPTION_ORDER_STATUSES
    if data.get("confirmed_at") is not None:
        assert is_iso8601_timestamp(data["confirmed_at"])
    if data.get("delivered_at") is not None:
        assert is_iso8601_timestamp(data["delivered_at"])


def assert_violation(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Violation")
    assert is_valid_uuid(data["resident_id"])
    assert is_valid_uuid(data["household_id"])
    assert is_valid_uuid(data["community_id"])
    assert data["violation_type"] in VIOLATION_TYPES
    assert is_iso8601_timestamp(data["occurred_at"])
    assert 1 <= len(data["evidence_uri"]) <= 500
    assert isinstance(data["base_deduction_points"], int)
    assert isinstance(data["repeat_count_in_window"], int)
    assert data["repeat_count_in_window"] >= 1
    assert isinstance(data["escalation_multiplier"], (int, float))
    assert isinstance(data["final_deduction_points"], int)
    assert data["status"] in VIOLATION_STATUSES
    if data.get("appeal_filed_at") is not None:
        assert is_iso8601_timestamp(data["appeal_filed_at"])
    assert is_iso8601_timestamp(data["appeal_deadline_at"])
    assert isinstance(data["appeal_round"], int)
    assert 0 <= data["appeal_round"] <= 2


def assert_ranking_period(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "RankingPeriod")
    assert is_valid_uuid(data["community_id"])
    assert data["granularity"] in RANKING_GRANULARITIES
    assert data["dimension"] in RANKING_DIMENSIONS
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in RANKING_PERIOD_STATUSES
    if data.get("published_at") is not None:
        assert is_iso8601_timestamp(data["published_at"])
    assert isinstance(data["leaderboard"], list)
    for entry in data["leaderboard"]:
        assert "subject_id" in entry
        assert entry["subject_kind"] in RANKING_DIMENSIONS
        assert isinstance(entry["score"], int)
        assert isinstance(entry["rank"], int) and entry["rank"] >= 1


def assert_audit_log(data: Dict[str, Any]) -> None:
    _assert_append_only_common(data, "AuditLog")
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    assert isinstance(data["actor_id"], str) and data["actor_id"]
    assert data["action"] in AUDIT_ACTIONS
    assert data["subject_kind"] in AUDIT_SUBJECT_KINDS
    assert is_valid_uuid(data["subject_id"])


# ---------------------------------------------------------------------------
# Cross-entity invariants
# ---------------------------------------------------------------------------
def assert_balance_reconciles_with_txns(
    household: Dict[str, Any], txns: List[Dict[str, Any]],
) -> None:
    """PRD §2.7: 'chronological tail of PointsTransaction rows reconciles to
    the household's current points_balance'."""
    total = sum(t["amount"] for t in txns)
    assert household["points_balance"] == total, (
        f"points_balance={household['points_balance']} does not match "
        f"sum(transactions.amount)={total}"
    )
    if txns:
        # last entry's balance_after must equal household.points_balance
        # if txns are sorted ascending by created_at.
        sorted_txns = sorted(txns, key=lambda t: t["created_at"])
        assert sorted_txns[-1]["balance_after"] == household["points_balance"]


def assert_lifetime_unchanged_across_violations(
    txns: List[Dict[str, Any]], expected_lifetime: int, household: Dict[str, Any],
) -> None:
    """PRD §3.6: violation overturn lifecycle conserves lifetime_points_earned."""
    assert household["lifetime_points_earned"] == expected_lifetime, (
        f"lifetime_points_earned={household['lifetime_points_earned']} != "
        f"expected {expected_lifetime}"
    )


def find_audit_entries(
    entries: Iterable[Dict[str, Any]],
    action: Optional[str] = None,
    subject_kind: Optional[str] = None,
    subject_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    matched: List[Dict[str, Any]] = []
    for e in entries:
        if action is not None and e.get("action") != action:
            continue
        if subject_kind is not None and e.get("subject_kind") != subject_kind:
            continue
        if subject_id is not None and e.get("subject_id") != subject_id:
            continue
        matched.append(e)
    return matched


def find_transactions_of_kind(
    txns: Iterable[Dict[str, Any]], kind: str,
) -> List[Dict[str, Any]]:
    return [t for t in txns if t.get("kind") == kind]


__all__ = [
    "COMMUNITY_STATUSES",
    "HOUSEHOLD_STATUSES",
    "IDENTITY_STATUSES",
    "ACCOUNT_STATUSES",
    "RESIDENT_RELATIONS",
    "GARBAGE_CATEGORIES",
    "SCORING_METHODS",
    "POINT_RULE_STATUSES",
    "DISPOSAL_STATUSES",
    "POINTS_TXN_KINDS",
    "MALL_ITEM_STATUSES",
    "MALL_CHANNELS",
    "REDEMPTION_ORDER_STATUSES",
    "VIOLATION_TYPES",
    "VIOLATION_STATUSES",
    "RANKING_GRANULARITIES",
    "RANKING_DIMENSIONS",
    "RANKING_PERIOD_STATUSES",
    "AUDIT_ACTIONS",
    "AUDIT_SUBJECT_KINDS",
    "assert_community",
    "assert_household",
    "assert_resident",
    "assert_point_rule",
    "assert_disposal",
    "assert_points_transaction",
    "assert_mall_item",
    "assert_redemption_order",
    "assert_violation",
    "assert_ranking_period",
    "assert_audit_log",
    "assert_balance_reconciles_with_txns",
    "assert_lifetime_unchanged_across_violations",
    "find_audit_entries",
    "find_transactions_of_kind",
]
