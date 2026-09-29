"""Entity-shape and invariant assertions.

Every ``assert_<entity>`` helper checks the identity/audit envelope and the
declared field set, then applies any ``expected`` field values the caller
supplies. The envelope split matters: four representations are append-only
evidence records that carry only ``id`` and ``created_at``, while every other
entity also carries ``updated_at`` and a monotonic ``version``.
"""

from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_identity(entity: Dict[str, Any], label: str) -> None:
    assert "id" in entity, f"{label} is missing 'id'"
    assert is_valid_uuid(entity["id"]), f"{label}.id is not a UUID: {entity['id']!r}"
    assert "created_at" in entity, f"{label} is missing 'created_at'"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"{label}.created_at is not an ISO 8601 UTC timestamp: {entity['created_at']!r}"
    )


def assert_mutable_envelope(entity: Dict[str, Any], label: str = "entity") -> None:
    """Identity plus the mutation-tracking fields of a mutable entity."""
    _assert_identity(entity, label)
    assert "updated_at" in entity, f"{label} is missing 'updated_at'"
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"{label}.updated_at is not an ISO 8601 UTC timestamp: {entity['updated_at']!r}"
    )
    assert isinstance(entity.get("version"), int), f"{label}.version is not an integer"
    assert entity["version"] >= 1, f"{label}.version must start at 1, got {entity['version']}"


def assert_append_only_record(entity: Dict[str, Any], label: str = "record") -> None:
    """An append-only evidence record: id and created_at only.

    ``updated_at`` and ``version`` must be absent because the record is never
    revised after it is written.
    """
    _assert_identity(entity, label)
    assert "updated_at" not in entity, (
        f"{label} is append-only and must not expose 'updated_at'"
    )
    assert "version" not in entity, f"{label} is append-only and must not expose 'version'"


def _assert_fields(
    entity: Dict[str, Any], required: Iterable[str], label: str, expected: Optional[Dict[str, Any]]
) -> None:
    for field in required:
        assert field in entity, f"{label} is missing '{field}'"
    for field, value in (expected or {}).items():
        assert entity.get(field) == value, (
            f"{label}.{field}: expected {value!r}, got {entity.get(field)!r}"
        )


# ─── Mutable entities ─────────────────────────────────────────────────
def assert_store(store: Dict[str, Any], expected: Optional[Dict[str, Any]] = None) -> None:
    assert_mutable_envelope(store, "Store")
    _assert_fields(
        store,
        (
            "store_code",
            "name",
            "hot_case_slot_capacity",
            "pickup_slot_capacity",
            "is_fuel_site",
            "current_daypart",
            "daypart_epoch",
            "hot_case_slots_used",
            "waste_cost_cents_mtd",
            "rework_waste_cents_mtd",
        ),
        "Store",
        expected,
    )


def assert_holding_unit(unit: Dict[str, Any], expected: Optional[Dict[str, Any]] = None) -> None:
    assert_mutable_envelope(unit, "HoldingUnit")
    _assert_fields(
        unit,
        (
            "store_id",
            "unit_code",
            "unit_type",
            "min_temp_f",
            "max_temp_f",
            "slot_count",
            "status",
            "consecutive_out_of_range_count",
            "last_temp_log_at",
        ),
        "HoldingUnit",
        expected,
    )


def assert_menu_item(item: Dict[str, Any], expected: Optional[Dict[str, Any]] = None) -> None:
    assert_mutable_envelope(item, "MenuItem")
    _assert_fields(
        item,
        (
            "sku",
            "name",
            "station",
            "fulfillment_mode",
            "base_price_cents",
            "unit_food_cost_cents",
            "valid_dayparts",
            "prep_seconds",
            "bake_minutes",
            "hold_minutes",
            "included_premium_count",
            "is_catering_eligible",
        ),
        "MenuItem",
        expected,
    )


def assert_promotion_rule(rule: Dict[str, Any], expected: Optional[Dict[str, Any]] = None) -> None:
    assert_mutable_envelope(rule, "PromotionRule")
    _assert_fields(
        rule,
        ("code", "kind", "discount_kind", "max_discount_cents", "valid_dayparts",
         "stacking_rank", "status"),
        "PromotionRule",
        expected,
    )


def assert_loyalty_account(
    account: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> None:
    assert_mutable_envelope(account, "LoyaltyAccount")
    _assert_fields(
        account,
        (
            "member_code",
            "points_balance",
            "lifetime_points_earned",
            "lifetime_points_redeemed",
            "points_reversed_total",
            "tier",
        ),
        "LoyaltyAccount",
        expected,
    )


def assert_staffing_plan(plan: Dict[str, Any], expected: Optional[Dict[str, Any]] = None) -> None:
    assert_mutable_envelope(plan, "StaffingPlan")
    _assert_fields(
        plan,
        (
            "store_id",
            "service_date",
            "daypart",
            "forecast_txn_count",
            "mto_share_bp",
            "peak_multiplier_bp",
            "planned_labor_minutes",
            "status",
        ),
        "StaffingPlan",
        expected,
    )


def assert_production_batch(
    batch: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> None:
    assert_mutable_envelope(batch, "ProductionBatch")
    _assert_fields(
        batch,
        (
            "store_id",
            "menu_item_id",
            "holding_unit_id",
            "slot_index",
            "planned_qty",
            "bake_start_at",
            "occupancy_end_at",
            "baked_qty",
            "remaining_qty",
            "reserved_qty",
            "sold_qty",
            "discarded_qty",
            "hold_started_at",
            "hold_expires_at",
            "status",
        ),
        "ProductionBatch",
        expected,
    )


def assert_corrective_action(
    action: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> None:
    assert_mutable_envelope(action, "CorrectiveAction")
    _assert_fields(
        action,
        ("temperature_log_id", "action_taken", "status", "opened_by_user_id",
         "verified_by_user_id", "verified_at"),
        "CorrectiveAction",
        expected,
    )


def assert_order(order: Dict[str, Any], expected: Optional[Dict[str, Any]] = None) -> None:
    assert_mutable_envelope(order, "Order")
    _assert_fields(
        order,
        (
            "store_id",
            "channel",
            "production_status",
            "settlement_status",
            "subtotal_gross_cents",
            "promo_discount_cents",
            "service_fee_cents",
            "total_cents",
            "points_provisional",
            "points_final",
            "rework_count",
            "daypart_at_placement",
            "applied_promotion_id",
            "expected_ready_at",
        ),
        "Order",
        expected,
    )


def assert_order_line(line: Dict[str, Any], expected: Optional[Dict[str, Any]] = None) -> None:
    assert_mutable_envelope(line, "OrderLine")
    _assert_fields(
        line,
        (
            "order_id",
            "menu_item_id",
            "qty",
            "station",
            "unit_price_cents",
            "premium_surcharge_cents",
            "line_gross_cents",
            "line_discount_cents",
            "line_net_cents",
            "reserved_qty",
            "fulfillment_batch_id",
        ),
        "OrderLine",
        expected,
    )


def assert_kitchen_ticket(
    ticket: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> None:
    assert_mutable_envelope(ticket, "KitchenTicket")
    _assert_fields(
        ticket,
        (
            "order_id",
            "store_id",
            "station",
            "status",
            "prep_seconds",
            "lead_seconds",
            "sequence_position",
            "promised_ready_at",
            "started_by_user_id",
            "completed_by_user_id",
            "rework_count",
        ),
        "KitchenTicket",
        expected,
    )


# ─── Append-only evidence records ─────────────────────────────────────
def assert_modifier_option(
    option: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> None:
    assert_append_only_record(option, "ModifierOption")
    _assert_fields(
        option,
        ("menu_item_id", "code", "modifier_class", "price_delta_cents", "is_premium", "max_qty"),
        "ModifierOption",
        expected,
    )


def assert_fuel_transaction(
    txn: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> None:
    assert_append_only_record(txn, "FuelTransaction")
    _assert_fields(
        txn,
        ("loyalty_account_id", "gallons", "price_per_gallon_cents", "fuel_spend_cents",
         "occurred_at"),
        "FuelTransaction",
        expected,
    )


def assert_waste_log(log: Dict[str, Any], expected: Optional[Dict[str, Any]] = None) -> None:
    assert_append_only_record(log, "WasteLog")
    _assert_fields(
        log,
        ("production_batch_id", "qty", "reason", "food_cost_cents", "retail_value_cents",
         "logged_by_user_id", "daypart_epoch"),
        "WasteLog",
        expected,
    )


def assert_temperature_log(log: Dict[str, Any], expected: Optional[Dict[str, Any]] = None) -> None:
    assert_append_only_record(log, "TemperatureLog")
    _assert_fields(
        log,
        ("holding_unit_id", "reading_f", "in_range", "logged_by_user_id", "recorded_at"),
        "TemperatureLog",
        expected,
    )


# ─── Computed read ────────────────────────────────────────────────────
def assert_store_readiness(
    readiness: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> None:
    _assert_fields(
        readiness,
        (
            "temp_log_compliance_pct",
            "units_impaired_count",
            "units_locked_out_count",
            "open_corrective_actions_count",
            "food_cost_waste_cents_mtd",
            "retail_waste_exposure_cents",
            "readiness_status",
        ),
        "StoreReadiness",
        expected,
    )


# ─── Ledger invariants ────────────────────────────────────────────────
def assert_batch_quantity_ledger(batch: Dict[str, Any]) -> None:
    """The batch quantity ledger must balance at every observable moment.

    Baked units are always fully accounted for across the four disposition
    buckets, and reserved units are a subset of what is still on hand.
    """
    baked = batch["baked_qty"]
    remaining = batch["remaining_qty"]
    reserved = batch["reserved_qty"]
    sold = batch["sold_qty"]
    discarded = batch["discarded_qty"]
    assert remaining + reserved + sold + discarded == baked, (
        "batch quantity ledger does not balance: "
        f"remaining {remaining} + reserved {reserved} + sold {sold} + discarded "
        f"{discarded} != baked {baked}"
    )
    for field in ("baked_qty", "remaining_qty", "reserved_qty", "sold_qty", "discarded_qty"):
        assert batch[field] >= 0, f"ProductionBatch.{field} went negative: {batch[field]}"


def assert_loyalty_ledger(account: Dict[str, Any]) -> None:
    """The loyalty point counters must stay internally consistent.

    The spendable balance is what was earned less what was redeemed and less
    what was reversed, and no counter may go negative.
    """
    balance = account["points_balance"]
    earned = account["lifetime_points_earned"]
    redeemed = account["lifetime_points_redeemed"]
    reversed_total = account["points_reversed_total"]
    assert balance == earned - redeemed - reversed_total, (
        "loyalty ledger does not balance: balance "
        f"{balance} != earned {earned} - redeemed {redeemed} - reversed {reversed_total}"
    )
    assert balance >= 0, f"points_balance went negative: {balance}"
    for field in ("lifetime_points_earned", "lifetime_points_redeemed", "points_reversed_total"):
        assert account[field] >= 0, f"LoyaltyAccount.{field} went negative: {account[field]}"


def assert_tier_for_lifetime_points(account: Dict[str, Any]) -> None:
    """Tier must be the band implied by lifetime points earned."""
    earned = account["lifetime_points_earned"]
    if earned >= 2000:
        expected = "ELITE"
    elif earned >= 500:
        expected = "PLUS"
    else:
        expected = "BASIC"
    assert account["tier"] == expected, (
        f"tier {account['tier']!r} does not match lifetime_points_earned {earned} "
        f"(expected {expected!r})"
    )


# ─── Response-shape helpers ───────────────────────────────────────────
def assert_no_content(response: Any) -> None:
    """A deletion must answer 204 with no body at all."""
    assert response.status_code == 204, (
        f"Expected HTTP 204 with no body, got {response.status_code}: {response.text}"
    )
    assert response.text == "", f"204 response must have an empty body, got {response.text!r}"


def assert_page_ids(rows: Iterable[Dict[str, Any]], expected_ids: Iterable[str]) -> None:
    """Compare a page's ids as a set, ignoring position."""
    actual = {row["id"] for row in rows}
    expected = set(expected_ids)
    assert actual == expected, f"page ids {sorted(actual)} != expected {sorted(expected)}"
