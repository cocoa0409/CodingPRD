"""Entity -> public JSON serializers. Computed fields are derived at read time.

Field names follow SCAFFOLD §1.1 exactly. Common fields (PRD §2.4):
id, created_at, updated_at, version on mutable entities; id + created_at only on
append-only ledgers (WalletTransaction, StarLedgerEntry).
"""
from services import projections


def member_out(m):
    lifetime = projections.lifetime_stars(m["id"])
    balance = projections.star_balance(m["id"])
    return {
        "id": m["id"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
        "email": m["email"],
        "full_name": m["full_name"],
        "birth_month_day": m["birth_month_day"],
        "star_balance": balance,
        "lifetime_stars": lifetime,
        "tier": projections.tier_for(lifetime),
        "last_birthday_reward_year": m["last_birthday_reward_year"],
        "status": m["status"],
    }


def store_out(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "name": s["name"],
        "timezone": s["timezone"],
        "slot_capacity": s["slot_capacity"],
        "prep_minutes": s["prep_minutes"],
        "status": s["status"],
    }


def menu_item_out(mi):
    return {
        "id": mi["id"],
        "created_at": mi["created_at"],
        "updated_at": mi["updated_at"],
        "version": mi["version"],
        "store_id": mi["store_id"],
        "name": mi["name"],
        "base_price_cents": mi["base_price_cents"],
        "category": mi["category"],
        "reward_eligible": mi["reward_eligible"],
        "available": mi["available"],
    }


def modifier_out(mo):
    return {
        "id": mo["id"],
        "created_at": mo["created_at"],
        "updated_at": mo["updated_at"],
        "version": mo["version"],
        "menu_item_id": mo["menu_item_id"],
        "group_code": mo["group_code"],
        "name": mo["name"],
        "price_delta_cents": mo["price_delta_cents"],
        "max_quantity": mo["max_quantity"],
    }


def card_out(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "member_id": c["member_id"],
        "balance_cents": projections.card_balance_cents(c["id"]),
        "auto_reload_enabled": c["auto_reload_enabled"],
        "auto_reload_threshold_cents": c["auto_reload_threshold_cents"],
        "auto_reload_amount_cents": c["auto_reload_amount_cents"],
    }


def wallet_txn_out(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "card_id": t["card_id"],
        "kind": t["kind"],
        "amount_cents": t["amount_cents"],
        "order_id": t["order_id"],
    }


def order_out(o):
    return {
        "id": o["id"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
        "member_id": o["member_id"],
        "store_id": o["store_id"],
        "pickup_slot_id": o["pickup_slot_id"],
        "applied_reward_id": o["applied_reward_id"],
        "subtotal_cents": o["subtotal_cents"],
        "reward_discount_cents": o["reward_discount_cents"],
        "tax_cents": o["tax_cents"],
        "total_cents": o["total_cents"],
        "stars_earned": o["stars_earned"],
        "fulfillment_status": o["fulfillment_status"],
        "payment_status": o["payment_status"],
        "pay_method": o["pay_method"],
    }


def order_line_out(l):
    return {
        "id": l["id"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
        "order_id": l["order_id"],
        "menu_item_id": l["menu_item_id"],
        "quantity": l["quantity"],
        "modifiers": l["modifiers"],
        "unit_price_cents": l["unit_price_cents"],
        "line_total_cents": l["line_total_cents"],
        "is_reward_redeemed": l["is_reward_redeemed"],
    }


def pickup_slot_out(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "store_id": s["store_id"],
        "window_start": s["window_start"],
        "window_end": s["window_end"],
        "reserved_count": projections.slot_reserved_count(s["id"]),
    }


def reward_out(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "member_id": r["member_id"],
        "kind": r["kind"],
        "star_cost": r["star_cost"],
        "max_discount_cents": r["max_discount_cents"],
        "expires_at": r["expires_at"],
        "status": r["status"],
        "reserved_by_order_id": r["reserved_by_order_id"],
    }


def star_ledger_out(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "member_id": e["member_id"],
        "kind": e["kind"],
        "delta_stars": e["delta_stars"],
        "order_id": e["order_id"],
    }


def refund_out(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "order_id": r["order_id"],
        "amount_cents": r["amount_cents"],
        "destination": r["destination"],
        "stars_reversed": r["stars_reversed"],
    }
