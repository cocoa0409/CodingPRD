"""Entity assertions and domain invariant checkers for the pricing API."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID with no prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1"
    )


def assert_market(data: dict) -> None:
    _assert_common(data, "Market")
    assert isinstance(data["market_code"], str) and 1 <= len(data["market_code"]) <= 32
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["currency_code"], str) and data["currency_code"]
    assert data["strategic_positioning"] in ("PRICE_LEADER", "AT_PARITY", "PREMIUM")
    assert 5000 <= data["strategic_index_target_bp"] <= 15000
    assert isinstance(data["index_tolerance_bp"], int) and data["index_tolerance_bp"] >= 0
    assert data["observed_index_bp"] is None or isinstance(data["observed_index_bp"], int)
    assert data["positioning_gap_bp"] is None or isinstance(data["positioning_gap_bp"], int)
    assert isinstance(data["insufficient_data_report_count"], int)
    assert data["pricing_posture"] in ("OPEN", "RESTRICTED", "FROZEN")


def assert_competitor(data: dict) -> None:
    _assert_common(data, "Competitor")
    assert is_valid_uuid(data["market_id"])
    assert isinstance(data["competitor_code"], str) and data["competitor_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["collection_method"] in ("ONLINE", "STORE_AUDIT", "HYBRID")
    assert data["tier"] in ("PRIMARY", "SECONDARY")
    assert isinstance(data["price_match_eligible"], bool)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "RETIRED")
    assert data["suspension_reason"] is None or isinstance(data["suspension_reason"], str)
    assert isinstance(data["confirmed_match_count"], int)
    assert isinstance(data["stale_match_count"], int)
    assert isinstance(data["stale_share_bp"], int)


def assert_product(data: dict) -> None:
    _assert_common(data, "Product")
    assert is_valid_uuid(data["market_id"])
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["category_code"], str) and data["category_code"]
    assert isinstance(data["brand"], str) and data["brand"]
    assert isinstance(data["own_price_cents"], int) and data["own_price_cents"] > 0
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] > 0
    assert 0 <= data["margin_floor_pct"] < 1
    assert isinstance(data["map_floor_cents"], int) and data["map_floor_cents"] >= 0
    assert isinstance(data["brand_repricing_restricted"], bool)
    assert isinstance(data["index_weight_bp"], int) and data["index_weight_bp"] > 0
    assert data["status"] in ("ACTIVE", "DISCONTINUED")
    assert data["last_price_change_at"] is None or is_iso8601_timestamp(data["last_price_change_at"])
    assert isinstance(data["price_change_count"], int) and data["price_change_count"] >= 0
    assert isinstance(data["effective_floor_cents"], int)


def assert_store(data: dict) -> None:
    _assert_common(data, "Store")
    assert is_valid_uuid(data["market_id"])
    assert isinstance(data["store_code"], str) and data["store_code"]
    assert isinstance(data["override_authority_cents"], int) and data["override_authority_cents"] >= 0
    assert (
        isinstance(data["label_printer_capacity_per_day"], int)
        and data["label_printer_capacity_per_day"] > 0
    )
    assert isinstance(data["label_slots_used_today"], int)
    assert isinstance(data["label_slots_remaining_today"], int)
    assert isinstance(data["override_budget_used_cents"], int)


def assert_match(data: dict) -> None:
    _assert_common(data, "CompetitorProductLink")
    assert is_valid_uuid(data["product_id"])
    assert is_valid_uuid(data["competitor_id"])
    assert data["match_method"] in ("IDENTIFIER", "ATTRIBUTE", "IMAGE")
    assert data["competitor_identifier"] is None or isinstance(data["competitor_identifier"], str)
    for field in ("identifier_score", "attribute_score", "image_score"):
        assert isinstance(data[field], int) and 0 <= data[field] <= 100
    assert isinstance(data["confidence_bp"], int) and 0 <= data["confidence_bp"] <= 10000
    assert data["confidence_variant"] in ("IDENTIFIER_ANCHORED", "ATTRIBUTE_BLEND")
    assert data["match_grade"] in ("EXACT", "CLOSE", "WEAK")
    assert isinstance(data["review_round"], int) and data["review_round"] >= 0
    assert data["status"] in ("PROPOSED", "UNDER_REVIEW", "CONFIRMED", "REJECTED")
    assert data["data_status"] in ("SUFFICIENT", "INSUFFICIENT")
    assert isinstance(data["gap_stale"], bool)


def assert_observation(data: dict) -> None:
    _assert_common(data, "PriceObservation")
    assert is_valid_uuid(data["link_id"])
    assert isinstance(data["observed_price_cents"], int) and data["observed_price_cents"] > 0
    assert data["collection_method"] in ("ONLINE", "STORE_AUDIT")
    assert is_iso8601_timestamp(data["observed_at"])
    assert isinstance(data["in_stock"], bool)
    assert isinstance(data["promo_flag"], bool)
    assert data["status"] in ("ACTIVE", "VOIDED")


def assert_index_report(data: dict) -> None:
    _assert_common(data, "PriceIndexReport")
    assert is_valid_uuid(data["market_id"])
    assert isinstance(data["category_code"], str) and data["category_code"]
    assert data["basis"] in ("MATCHED_BASKET", "IMPUTED_FULL_CATALOG")
    assert data["index_bp"] is None or isinstance(data["index_bp"], int)
    for field in (
        "candidate_product_count",
        "matched_product_count",
        "imputed_product_count",
        "excluded_product_count",
    ):
        assert isinstance(data[field], int) and data[field] >= 0
    assert data["data_sufficiency"] in ("SUFFICIENT", "INSUFFICIENT")
    assert data["positioning_verdict"] in (
        "ON_TARGET",
        "ABOVE_TARGET",
        "BELOW_TARGET",
        "INDETERMINATE",
    )
    assert data["perception_validation"] in ("CONFIRMS", "CONTRADICTS", "INDETERMINATE")
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED")


def assert_repricing_rule(data: dict) -> None:
    _assert_common(data, "RepricingRule")
    assert is_valid_uuid(data["market_id"])
    assert 5000 <= data["target_position_bp"] <= 15000
    assert 0 < data["max_change_pct"] <= 1
    assert isinstance(data["change_frequency_limit_days"], int)
    assert isinstance(data["priority"], int) and data["priority"] >= 0
    assert isinstance(data["brand_exclusions"], list)
    assert data["status"] in ("ACTIVE", "PAUSED")
    assert isinstance(data["applied_order_count"], int)


def assert_change_order(data: dict) -> None:
    _assert_common(data, "PriceChangeOrder")
    assert is_valid_uuid(data["product_id"])
    assert data["origin"] in ("AUTOMATED_RULE", "MANUAL", "PRICE_MATCH")
    assert isinstance(data["proposed_price_cents"], int) and data["proposed_price_cents"] > 0
    assert isinstance(data["effective_floor_cents"], int)
    assert isinstance(data["floor_binding"], bool)
    assert isinstance(data["band_breach"], bool)
    assert is_iso8601_timestamp(data["effective_from"])
    assert data["status"] in (
        "DRAFT",
        "PENDING_APPROVAL",
        "APPROVED",
        "EXECUTED",
        "SUSPENDED",
        "SUPERSEDED",
    )
    assert data["signage_status"] in ("NOT_REQUIRED", "QUEUED", "PRINTED", "RELEASED")


def assert_match_policy(data: dict) -> None:
    _assert_common(data, "PriceMatchPolicy")
    assert is_valid_uuid(data["market_id"])
    assert isinstance(data["eligible_competitor_tiers"], list) and data["eligible_competitor_tiers"]
    assert isinstance(data["excluded_category_codes"], list)
    assert isinstance(data["verification_required"], bool)
    assert 0 < data["max_match_discount_pct"] <= 1
    assert isinstance(data["daily_override_budget_cents"], int)
    assert isinstance(data["claim_window_hours"], int) and data["claim_window_hours"] > 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["honored_claim_count"], int)


def assert_claim(data: dict) -> None:
    _assert_common(data, "PriceMatchClaim")
    for field in ("policy_id", "product_id", "competitor_id", "store_id"):
        assert is_valid_uuid(data[field]), f"PriceMatchClaim.{field} must be a UUID"
    assert isinstance(data["claimed_price_cents"], int) and data["claimed_price_cents"] > 0
    assert is_iso8601_timestamp(data["claimed_observed_at"])
    assert isinstance(data["beat_bonus_cents"], int)
    assert isinstance(data["honored_price_cents"], int)
    assert isinstance(data["discount_cents"], int)
    assert data["required_approval_tier"] in ("ASSOCIATE", "MANAGER")
    assert isinstance(data["evidence_round"], int)
    assert data["status"] in (
        "SUBMITTED",
        "VERIFYING",
        "NEEDS_EVIDENCE",
        "VERIFIED",
        "REJECTED",
        "HONORED",
        "REVERSED",
    )


def assert_label_batch(data: dict) -> None:
    _assert_common(data, "LabelPrintBatch")
    assert is_valid_uuid(data["store_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["reserved_item_count"], int) and data["reserved_item_count"] >= 0
    assert isinstance(data["queued_order_ids"], list)
    assert isinstance(data["item_count"], int)
    assert data["item_count"] == data["reserved_item_count"] + len(data["queued_order_ids"]), (
        "item_count must equal reserved_item_count plus the number of queued entries"
    )
    assert data["status"] in ("SCHEDULED", "PRINTING", "COMPLETED", "CANCELLED")


def assert_override_log(data: dict) -> None:
    """An override log is append-only: only id and created_at, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "OverrideLog.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "OverrideLog.created_at must be ISO 8601"
    assert "updated_at" not in data, "OverrideLog carries no updated_at"
    assert "version" not in data, "OverrideLog carries no version"
    assert is_valid_uuid(data["claim_id"])
    assert data["direction"] in ("DEBIT", "CREDIT")
    assert data["approval_tier"] in ("ASSOCIATE", "MANAGER")
    assert isinstance(data["approved_by_role"], str) and data["approved_by_role"]
    assert isinstance(data["approved_by_user_id"], str) and data["approved_by_user_id"]
    assert isinstance(data["approved_discount_cents"], int)
    assert isinstance(data["honored_price_cents"], int)


def assert_label_slot_conservation(store: dict) -> None:
    """label_printer_capacity_per_day == label_slots_used_today + label_slots_remaining_today."""
    assert (
        store["label_printer_capacity_per_day"]
        == store["label_slots_used_today"] + store["label_slots_remaining_today"]
    ), (
        f"Slot conservation broken: {store['label_printer_capacity_per_day']} != "
        f"{store['label_slots_used_today']} + {store['label_slots_remaining_today']}"
    )


def assert_override_budget_conservation(store: dict, daily_override_budget_cents: int) -> None:
    """daily_override_budget_cents == override_budget_used_cents + override_budget_remaining_cents."""
    assert (
        daily_override_budget_cents
        == store["override_budget_used_cents"] + store["override_budget_remaining_cents"]
    ), (
        f"Budget conservation broken: {daily_override_budget_cents} != "
        f"{store['override_budget_used_cents']} + {store['override_budget_remaining_cents']}"
    )
