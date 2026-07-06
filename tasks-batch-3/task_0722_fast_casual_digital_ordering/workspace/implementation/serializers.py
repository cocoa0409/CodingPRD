"""Public field projections for each entity (strip internal _seq)."""

COMMON = ["id", "created_at", "updated_at", "version"]

FIELDS = {
    "store": COMMON + [
        "name", "state_code", "throughput_capacity_per_slot",
        "locker_count", "queue_status", "is_active",
    ],
    "menu_item": COMMON + [
        "store_id", "name", "base_price_cents", "base_calories",
        "allergen_tags", "is_available",
    ],
    "modifier": COMMON + [
        "menu_item_id", "name", "price_delta_cents", "calorie_delta",
        "adds_allergen_tags",
    ],
    "pickup_slot": COMMON + [
        "store_id", "window_start_utc", "window_end_utc", "channel",
        "reserved_count", "is_closed",
    ],
    "customer": COMMON + [
        "email", "full_name", "home_store_id", "allergen_blocklist",
        "wallet_credit_cents", "loyalty_account_id",
    ],
    "loyalty_account": COMMON + [
        "customer_id", "points_balance", "lifetime_points_earned", "tier",
    ],
    # PointsLedgerEntry: id + created_at only (immutable, no updated_at/version)
    "points_ledger_entry": [
        "id", "created_at", "loyalty_account_id", "order_id",
        "delta_points", "reason",
    ],
    "subscription_plan": COMMON + [
        "tier_name", "monthly_fee_cents", "free_delivery", "points_multiplier_bps",
    ],
    "subscription": COMMON + [
        "customer_id", "plan_id", "status", "current_period_end_utc",
    ],
    "order": COMMON + [
        "customer_id", "store_id", "pickup_slot_id", "subscription_id",
        "channel", "order_status", "settlement_status", "subtotal_cents",
        "delivery_fee_cents", "points_redeemed", "discount_cents",
        "wallet_applied_cents", "total_cents", "total_calories",
        "points_earned", "refunded_cents",
    ],
    "order_line": COMMON + [
        "order_id", "menu_item_id", "quantity", "modifier_ids",
        "line_total_cents", "line_calories", "effective_allergen_tags",
    ],
    "loyalty_challenge": COMMON + [
        "customer_id", "target_order_count", "bonus_points",
        "progress_count", "rounds_completed", "status",
    ],
}


def serialize(kind, entity):
    return {k: entity.get(k) for k in FIELDS[kind]}
