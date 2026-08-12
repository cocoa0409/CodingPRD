"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, mutable: bool = True):
    """PRD §2.4: every resource carries id (UUID) + created_at (ISO8601);
    mutable resources additionally carry updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    if mutable:
        assert "updated_at" in data, "mutable resource must carry updated_at"
        assert is_iso8601_timestamp(data["updated_at"]), (
            f"updated_at must be ISO 8601, got {data['updated_at']!r}"
        )
        assert isinstance(data.get("version"), int), "version must be an integer"
    else:
        assert "updated_at" not in data, "append-only resource must omit updated_at"
        assert "version" not in data, "append-only resource must omit version"


def assert_brand(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["category"] in [
        "BEVERAGE", "AUTOMOTIVE", "TECH", "FOOD", "BEAUTY", "OTHER",
    ]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["watchlist_flag"], bool)


def assert_brief(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["brand_id"])
    assert isinstance(data["title"], str)
    assert isinstance(data["objective"], str)
    assert isinstance(data["budget_cents"], int)
    assert isinstance(data["remaining_budget_cents"], int)
    assert data["status"] in ["DRAFT", "OPEN", "CLOSED"]


def assert_series(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["network_name"], str)
    assert data["clearance_policy"] in ["STANDARD", "STRICT"]


def assert_episode(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["series_id"])
    assert isinstance(data["episode_number"], int) and data["episode_number"] >= 1
    assert isinstance(data["runtime_seconds"], int) and data["runtime_seconds"] > 0
    assert isinstance(data["air_date"], str)
    assert isinstance(data["created_by_user_id"], str)
    assert data["status"] in ["SCRIPT_REVIEW", "LOCKED", "AIRED", "VERIFIED"]


def assert_opportunity(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["episode_id"])
    assert isinstance(data["scene_description"], str)
    assert isinstance(data["start_timecode_seconds"], int)
    assert isinstance(data["end_timecode_seconds"], int)
    assert isinstance(data["estimated_exposure_seconds"], int)
    assert data["status"] in [
        "IDENTIFIED", "PITCHED", "RESERVED", "CONSUMED", "WITHDRAWN",
    ]


def assert_proposal(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["brief_id"])
    assert is_valid_uuid(data["opportunity_id"])
    assert isinstance(data["proposed_fee_cents"], int)
    assert isinstance(data["guaranteed_seconds"], int)
    assert isinstance(data["guaranteed_verbal_mentions"], int)
    assert isinstance(data["cross_promo_owed_count"], int)
    assert isinstance(data["rate_cents_per_second"], (int, float))
    assert isinstance(data["terms_revision"], int)
    assert data["status"] in [
        "DRAFT", "PRODUCTION_REVIEW", "NETWORK_REVIEW", "REVISION_REQUESTED",
        "APPROVED", "REJECTED", "CONTRACTED", "WITHDRAWN",
    ]


def assert_contract(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["proposal_id"])
    assert is_valid_uuid(data["episode_id"])
    assert isinstance(data["base_fee_cents"], int)
    assert isinstance(data["guaranteed_seconds"], int)
    assert isinstance(data["guaranteed_verbal_mentions"], int)
    assert isinstance(data["rate_cents_per_second"], (int, float))
    assert isinstance(data["cross_promo_owed_count"], int)
    assert data["provisional_value_cents"] is None or isinstance(
        data["provisional_value_cents"], int
    )
    assert isinstance(data["bonus_cents"], int)
    assert isinstance(data["makegood_total_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["final_settlement_cents"] is None or isinstance(
        data["final_settlement_cents"], int
    )
    assert data["status"] in [
        "PENDING_SIGNATURE", "ACTIVE", "UNDER_VERIFICATION",
        "MAKEGOOD_REQUIRED", "SETTLED", "TERMINATED",
    ]


def assert_shipment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["contract_id"])
    assert isinstance(data["item_description"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert data["status"] in [
        "PENDING", "DISPATCHED", "DELIVERED", "STAGED",
        "RETURN_REQUESTED", "IN_RETURN", "RETURNED", "CANCELLED",
    ]


def assert_continuity_record(data: dict):
    """PRD §2.4: ContinuityRecord carries ONLY id + created_at among common
    fields (no updated_at, no version)."""
    _assert_common(data, mutable=False)
    assert is_valid_uuid(data["contract_id"])
    assert is_valid_uuid(data["shipment_id"])
    assert isinstance(data["scene_timecode_seconds"], int)
    assert isinstance(data["note"], str)
    assert data["status"] in ["LOGGED", "VOID"]


def assert_clearance(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["episode_id"])
    assert is_valid_uuid(data["brand_id"])
    assert data["category"] in [
        "BEVERAGE", "AUTOMOTIVE", "TECH", "FOOD", "BEAUTY", "OTHER",
    ]
    assert data.get("risk_score") is None or isinstance(data["risk_score"], int)
    assert data.get("decided_by_user_id") is None or isinstance(
        data["decided_by_user_id"], str
    )
    assert data["status"] in ["REQUESTED", "GRANTED", "DENIED", "RELEASED"]


def assert_airing_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["episode_id"])
    assert is_valid_uuid(data["contract_id"])
    segs = data["measured_segments_seconds"]
    assert isinstance(segs, list) and len(segs) > 0
    assert all(isinstance(s, (int, float)) and s > 0 for s in segs)
    assert isinstance(data["measured_verbal_mentions"], int)
    assert isinstance(data["measured_seconds"], (int, float))
    assert isinstance(data["measured_value_cents"], int)
    assert isinstance(data["filed_by_user_id"], str)
    assert data["status"] in ["FILED", "VERIFIED", "DISPUTED", "RE_MEASURED"]


def assert_makegood_credit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["contract_id"])
    assert isinstance(data["amount_cents"], int)
    assert data["reason"] in ["EXPOSURE_SHORTFALL", "VERBAL_MISS", "COMBINED"]
    assert data["status"] in ["PENDING", "WAIVED"]


def assert_cross_promo(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["contract_id"])
    assert isinstance(data["owed_count"], int)
    assert isinstance(data["fulfilled_count"], int)
    assert data["status"] in ["OWED", "PARTIALLY_FULFILLED", "FULFILLED"]


def assert_disclosure(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["contract_id"])
    assert isinstance(data["disclosure_text"], str)
    assert data["status"] in ["DRAFT", "FILED", "ACKNOWLEDGED"]


def assert_ledger(data: dict):
    """PRD §3.5: ledger view exposes the six monetary fields."""
    for key in (
        "base_fee_cents",
        "bonus_cents",
        "makegood_total_cents",
        "outstanding_balance_cents",
    ):
        assert isinstance(data[key], int), f"{key} must be int, got {data.get(key)!r}"
    assert data.get("provisional_value_cents") is None or isinstance(
        data["provisional_value_cents"], int
    )
    assert data.get("final_settlement_cents") is None or isinstance(
        data["final_settlement_cents"], int
    )
