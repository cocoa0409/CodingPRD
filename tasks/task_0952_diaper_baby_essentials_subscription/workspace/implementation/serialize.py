"""Entity serializers.

Every datetime leaves through `envelope.jsonable`, which renders it as an ISO
8601 UTC instant with exactly three fractional digits, and every calendar date
as YYYY-MM-DD. No field can therefore render as an HTTP-date.

Serialization always happens AFTER `store.touch()` has bumped the version, so a
mutation response always reports the value *after* its own increment (PRD 2.4).
"""

import services
from store import db

COMMON = ("id", "created_at", "updated_at", "version")
APPEND_ONLY = ("id", "created_at")


def _pick(row, keys):
    out = {}
    for key in keys:
        out[key] = row.get(key)
    return out


def account(row):
    out = _pick(row, COMMON + (
        "email", "full_name", "status", "verification_token",
        "payment_method_on_file", "referral_code", "referred_by_code",
        "loyalty_account_id", "suspended_reason"))
    out["available_credit_cents"] = services.available_credit_cents(row["id"])
    out["next_charge_estimate_cents"] = services.next_charge_estimate_cents(
        row["id"], True)
    return out


def child(row):
    return _pick(row, COMMON + (
        "account_id", "name", "birth_date", "weight_grams", "stage",
        "stage_pinned", "hypoallergenic_required", "archived"))


def allergen_flag(row):
    return _pick(row, APPEND_ONLY + ("child_id", "allergen_tag", "severity", "note"))


def plan(row):
    return _pick(row, COMMON + (
        "code", "name", "default_pack_count", "promo_discount_pct",
        "allows_hypoallergenic", "status"))


def sku(row):
    return _pick(row, COMMON + (
        "code", "name", "stage", "line", "pack_size_units", "pack_price_cents",
        "allergen_tags", "stock_packs", "status"))


def subscription(row):
    out = _pick(row, COMMON + (
        "account_id", "plan_id", "child_id", "pack_count",
        "consumption_rate_per_day", "cadence_override_days",
        "cadence_interval_days", "anchor_date", "lifecycle_state",
        "billing_state", "free_shipping_eligible", "cancelled_at"))
    out["cumulative_pause_days"] = services.recompute_pause_days(row)
    out["auto_resize_count_in_period"] = services.auto_resize_count_in_period(row["id"])
    out["next_charge_cents"] = services.next_charge_cents(row["id"])
    return out


def cycle(row):
    return _pick(row, COMMON + (
        "subscription_id", "sequence_number", "window_start", "window_end",
        "ship_date", "cutoff_at", "status", "payment_status",
        "stage_at_allocation", "subtotal_cents", "shipping_cents",
        "gift_credit_applied_cents", "referral_credit_applied_cents",
        "loyalty_redemption_applied_cents", "loyalty_points_redeemed",
        "promo_discount_cents", "total_due_cents", "charged_cash_cents",
        "retained_cash_cents", "points_earned", "dispatched_at", "delivered_at"))


def cycle_line(row):
    return _pick(row, COMMON + (
        "cycle_id", "sku_id", "quantity_packs", "unit_price_cents",
        "line_total_cents", "status", "substitution_attempts",
        "short_filled_units"))


def resize_event(row):
    return _pick(row, APPEND_ONLY + (
        "subscription_id", "child_id", "target_cycle_id", "origin",
        "from_stage", "to_stage", "status", "measured_weight_grams",
        "reject_reason"))


def skip_record(row):
    return _pick(row, APPEND_ONLY + (
        "subscription_id", "cycle_id", "status", "anchor_before", "anchor_after"))


def pause_record(row):
    sub = db.subscriptions.get(row["subscription_id"])
    if sub is not None:
        services.recompute_pause_days(sub)
    return _pick(row, COMMON + (
        "subscription_id", "start_date", "end_date", "status",
        "actual_end_date", "consumed_days"))


def registry(row):
    services.recompute_registry(row)
    return _pick(row, COMMON + (
        "owner_account_id", "child_id", "title", "status", "reopen_count",
        "completion_pct", "inflight_gift_count"))


def registry_item(row):
    return _pick(row, COMMON + (
        "registry_id", "sku_id", "requested_quantity", "fulfilled_quantity",
        "status"))


def gift_order(row):
    return _pick(row, COMMON + (
        "registry_item_id", "purchaser_account_id", "quantity", "gift_message",
        "paid_cents", "claim_mode", "status", "paid_at", "claimed_at"))


def credit(row):
    return _pick(row, COMMON + (
        "account_id", "source_gift_order_id", "source_referral_id",
        "credit_type", "issued_cents", "consumed_cents", "remaining_cents",
        "forfeited_cents", "refundable", "status", "expires_at"))


def shipment(row):
    return _pick(row, COMMON + (
        "account_id", "cycle_id", "gift_order_id", "status", "exception_count",
        "service_level", "eta_days", "dispatched_at", "delivered_at"))


def loyalty_account(row):
    services.recompute_wallet_balance(row)
    return _pick(row, COMMON + (
        "account_id", "points_balance", "tier", "trailing_earned_points",
        "tier_evaluated_at"))


def points_ledger_entry(row):
    return _pick(row, APPEND_ONLY + (
        "loyalty_account_id", "cycle_id", "entry_type", "delta_points",
        "earn_base_cents", "tier_multiplier_applied", "expires_at"))


def referral(row):
    return _pick(row, COMMON + (
        "referrer_account_id", "referee_account_id", "vesting_cycle_id", "code",
        "status", "credit_cents", "vested_at", "expires_at"))


def refund(row):
    return _pick(row, COMMON + (
        "account_id", "cycle_id", "gift_order_id", "reason", "requested_cents",
        "refunded_cash_cents", "restock_fee_cents", "points_clawed_back",
        "credits_restored_cents", "status", "approved_by_user_id",
        "settled_by_user_id"))


def substitution_event(row):
    return _pick(row, APPEND_ONLY + (
        "cycle_line_id", "from_sku_id", "to_sku_id", "ladder_rung", "outcome",
        "price_delta_cents", "reason"))
