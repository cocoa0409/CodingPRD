"""Entity assertions and domain invariant checkers (PRD §2.2–§2.9, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value: str) -> datetime:
    """Parse an ISO-8601 UTC instant (with or without fractional digits)."""
    assert isinstance(value, str), f"Expected ISO-8601 string, got {value!r}"
    assert is_iso8601_timestamp(value), f"Not a valid ISO 8601 timestamp: {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected_iso: str, label: str = "instant"):
    """Two instants are equal when they denote the same second, regardless of
    fractional-digit formatting."""
    a = _parse_instant(actual)
    e = _parse_instant(expected_iso)
    assert a == e, f"{label}: expected {expected_iso}, got {actual}"


def _assert_common_fields(data: dict):
    """PRD §2.4: id, created_at, updated_at, version on every resource."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be an integer, got {data.get('version')!r}"
    )


def assert_community(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["incentive_budget_total_cents"], int)
    assert data["incentive_budget_total_cents"] >= 0
    assert isinstance(data["incentive_budget_remaining_cents"], int)
    assert data["status"] in ("SETUP", "SELLING")


def assert_price_phase(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["community_id"], str)
    assert isinstance(data["phase_name"], str) and data["phase_name"]
    assert isinstance(data["uplift_pct"], (int, float))
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert data["status"] in ("SCHEDULED", "ACTIVE", "EXPIRED")


def assert_lot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["community_id"], str)
    assert isinstance(data["lot_number"], str) and data["lot_number"]
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] > 0
    assert data["lot_type"] in ("STANDARD", "CORNER", "VIEW", "CUL_DE_SAC")
    assert isinstance(data["view_adjustment_cents"], int)
    assert data["view_adjustment_cents"] >= 0
    if data.get("release_price_cents") is not None:
        assert isinstance(data["release_price_cents"], int)
    assert isinstance(data["release_count"], int) and data["release_count"] >= 0
    if data.get("reserved_buyer_id") is not None:
        assert isinstance(data["reserved_buyer_id"], str)
    if data.get("hold_expires_at") is not None:
        assert is_iso8601_timestamp(data["hold_expires_at"])
    assert data["status"] in ("DRAFT", "RELEASED", "RESERVED", "SOLD", "CLOSED")


def assert_home_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["community_id"], str)
    assert isinstance(data["plan_name"], str) and data["plan_name"]
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] > 0
    assert isinstance(data["elevations"], list) and len(data["elevations"]) >= 1
    names = [e["name"] for e in data["elevations"]]
    assert len(names) == len(set(names)), "elevation names unique within the plan"
    for entry in data["elevations"]:
        assert isinstance(entry["name"], str) and entry["name"]
        assert isinstance(entry["price_cents"], int) and entry["price_cents"] >= 0


def assert_option_catalog_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["community_id"], str)
    assert isinstance(data["option_name"], str) and data["option_name"]
    assert data["category"] in (
        "STRUCTURAL", "KITCHEN", "BATH", "FLOORING", "ELECTRICAL", "OUTDOOR",
    )
    assert isinstance(data["price_cents"], int) and data["price_cents"] > 0
    stages = ("PRE_CONSTRUCTION", "FOUNDATION", "FRAMING", "DRYWALL",
              "FINAL_WALKTHROUGH")
    assert data["cutoff_stage"] in stages
    assert data["install_stage"] in stages


def assert_buyer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]


def assert_purchase_agreement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["buyer_id"], str)
    assert isinstance(data["lot_id"], str)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["community_id"], str)
    assert isinstance(data["elevation_name"], str)
    assert isinstance(data["earnest_money_deposited_cents"], int)
    assert data["earnest_money_deposited_cents"] >= 100_000
    assert data["status"] in (
        "DRAFT", "PENDING_CONTINGENCIES", "CONTINGENCIES_CLEARED",
        "CLOSED", "CANCELLED",
    )
    for tracker in ("financing_contingency_status", "appraisal_contingency_status",
                    "sale_of_home_contingency_status"):
        assert data[tracker] in ("PENDING", "CLEARED", "WAIVED"), tracker
    assert data["current_stage"] in (
        "NOT_STARTED", "PRE_CONSTRUCTION", "FOUNDATION", "FRAMING",
        "DRYWALL", "FINAL_WALKTHROUGH", "COMPLETE",
    )
    for money in ("options_total_cents", "change_fees_total_cents",
                  "incentives_total_cents"):
        assert isinstance(data[money], int) and data[money] >= 0, money
    for nullable in ("lot_price_snapshot_cents", "plan_price_snapshot_cents",
                     "elevation_price_snapshot_cents", "provisional_total_cents",
                     "final_total_cents", "refund_amount_cents",
                     "forfeited_amount_cents"):
        if data.get(nullable) is not None:
            assert isinstance(data[nullable], int), nullable
    for ts in ("estimated_close_standard", "estimated_close_padded",
               "warranty_enrolled_at"):
        if data.get(ts) is not None:
            assert is_iso8601_timestamp(data[ts]), ts
    assert isinstance(data["slippage_flag"], bool)
    if data.get("cancel_reason") is not None:
        assert data["cancel_reason"] in (
            "BUYER_DEFAULT", "BUILDER_DEFAULT", "CONTINGENCY_EXPIRED",
        )
    assert data["warranty_status"] in ("NONE", "ENROLLED", "ACKNOWLEDGED")
    assert isinstance(data["warranty_term_months"], int)
    assert data["warranty_term_months"] >= 0


def assert_option_selection(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["agreement_id"], str)
    assert isinstance(data["option_item_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)
    assert isinstance(data["change_fee_cents"], int) and data["change_fee_cents"] >= 0
    stages = ("NOT_STARTED", "PRE_CONSTRUCTION", "FOUNDATION", "FRAMING",
              "DRYWALL", "FINAL_WALKTHROUGH", "COMPLETE")
    assert data["selected_at_stage"] in stages
    if data.get("confirmed_at_stage") is not None:
        assert data["confirmed_at_stage"] in stages
    assert data["status"] in ("SELECTED", "CONFIRMED", "INSTALLED", "CANCELLED")
    if data.get("cancel_reason") is not None:
        assert data["cancel_reason"] in (
            "BUYER_REQUEST", "CUTOFF_EXPIRED", "AGREEMENT_CANCELLED",
        )


def assert_construction_milestone(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["agreement_id"], str)
    assert data["stage"] in (
        "PRE_CONSTRUCTION", "FOUNDATION", "FRAMING", "DRYWALL",
        "FINAL_WALKTHROUGH",
    )
    assert isinstance(data["sequence_no"], int) and 1 <= data["sequence_no"] <= 5
    assert isinstance(data["planned_duration_days"], int)
    assert data["planned_duration_days"] > 0
    assert data["status"] in ("NOT_STARTED", "COMPLETE")
    for ts in ("completed_at", "buyer_notified_at"):
        if data.get(ts) is not None:
            assert is_iso8601_timestamp(data[ts]), ts


def assert_incentive_request(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["agreement_id"], str)
    assert data["incentive_type"] in (
        "RATE_BUYDOWN", "CLOSING_COST_CREDIT", "PRICE_REDUCTION",
    )
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED", "REVOKED")
    assert isinstance(data["auto_approved"], bool)
    if data.get("decided_at") is not None:
        assert is_iso8601_timestamp(data["decided_at"])


def assert_refund_invariant(agreement: dict):
    """PRD §3.8: refund + forfeited always equals the deposited earnest money."""
    total = agreement["refund_amount_cents"] + agreement["forfeited_amount_cents"]
    assert total == agreement["earnest_money_deposited_cents"], (
        f"refund {agreement['refund_amount_cents']} + forfeited "
        f"{agreement['forfeited_amount_cents']} != earnest "
        f"{agreement['earnest_money_deposited_cents']}"
    )


def assert_budget_conservation(community: dict, approved_amounts_sum: int):
    """PRD §2.8: remaining + sum(APPROVED amounts) == incentive_budget_total."""
    assert (
        community["incentive_budget_remaining_cents"] + approved_amounts_sum
        == community["incentive_budget_total_cents"]
    ), (
        f"Ledger not conserved: {community['incentive_budget_remaining_cents']} "
        f"+ {approved_amounts_sum} != {community['incentive_budget_total_cents']}"
    )
