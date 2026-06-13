"""Entity -> public JSON serializers.

Each serializer returns the exact field set the PRD/SCAFFOLD describes for that
entity. Internal-only keys (e.g. hold_placed_at) are never exposed.
"""

COMMON = ["id", "created_at", "updated_at", "version"]


def _pick(entity, fields):
    return {f: entity.get(f) for f in fields}


def rate_card(e):
    return _pick(e, COMMON + [
        "name", "per_game_cents", "per_hour_cents", "block_minutes",
        "peak_multiplier_bps", "peak_start_hour", "peak_end_hour", "deposit_pct_bps",
    ])


def lane(e):
    return _pick(e, COMMON + ["number", "max_bowlers", "status"])


def bay(e):
    return _pick(e, COMMON + ["name", "capacity", "cleanup_buffer_minutes", "status"])


def customer(e):
    return _pick(e, COMMON + [
        "email", "full_name", "deposit_balance_cents", "wallet_credit_cents", "status",
    ])


def party_package(e):
    return _pick(e, COMMON + [
        "name", "base_cents", "included_guests", "extra_guest_cents",
        "max_guests", "included_lane_hours",
    ])


def food_item(e):
    return _pick(e, COMMON + ["name", "unit_cents", "taxable"])


def rental_item(e):
    return _pick(e, COMMON + [
        "kind", "label", "unit_price_cents", "total_count",
        "out_on_rent_count", "available_count",
    ])


def reservation(e):
    return _pick(e, COMMON + [
        "customer_id", "rate_card_id", "resource_kind", "lane_id", "bay_id",
        "party_package_id", "origin", "pricing_mode", "start_at", "end_at",
        "bowler_count", "game_count", "guest_count",
        "lane_subtotal_cents", "package_subtotal_cents", "food_subtotal_cents",
        "rental_subtotal_cents", "quoted_total_cents", "held_deposit_cents",
        "refund_cents", "status", "cancelled_at",
    ])


def food_line(e):
    # FoodOrderLine carries only id + created_at (PRD §2.4) — no updated_at/version.
    return _pick(e, ["id", "created_at"] + [
        "reservation_id", "food_item_id", "quantity",
        "unit_cents_snapshot", "taxable_snapshot", "line_total_cents",
    ])


def rental_line(e):
    return _pick(e, COMMON + [
        "reservation_id", "rental_item_id", "quantity",
        "unit_price_snapshot", "line_total_cents", "status",
    ])


def league(e):
    return _pick(e, COMMON + [
        "name", "rate_card_id", "season_night_count", "lanes_per_night",
        "weekly_fee_cents", "season_fee_quote_cents", "season_fee_accrued_cents", "status",
    ])


def league_night(e):
    return _pick(e, COMMON + [
        "league_id", "night_index", "start_at", "end_at",
        "reserved_lane_ids", "status", "night_fee_cents",
    ])
