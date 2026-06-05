"""Convert internal records into API output dicts.

Internal bookkeeping keys (those prefixed with "_") are stripped. Each entity
serializer lists the fields exactly as the PRD/scaffold define them, in a stable
order, so output never leaks internal state.
"""


def _common(rec, with_version=True):
    out = {"id": rec["id"], "created_at": rec["created_at"]}
    if with_version:
        out["updated_at"] = rec["updated_at"]
        out["version"] = rec["version"]
    return out


def product_out(r):
    out = _common(r)
    out.update({
        "name": r["name"],
        "base_earn_rate_bps": r["base_earn_rate_bps"],
        "signup_bonus_points": r["signup_bonus_points"],
        "signup_bonus_spend_threshold_cents": r["signup_bonus_spend_threshold_cents"],
        "signup_bonus_window_days": r["signup_bonus_window_days"],
        "tier_thresholds": r["tier_thresholds"],
        "points_expiry_months": r["points_expiry_months"],
        "status": r["status"],
    })
    return out


def cashback_category_out(r):
    out = _common(r)
    out.update({
        "card_product_id": r["card_product_id"],
        "code": r["code"],
        "earn_multiplier_bps": r["earn_multiplier_bps"],
        "status": r["status"],
    })
    return out


def quarterly_category_out(r):
    out = _common(r)
    out.update({
        "card_product_id": r["card_product_id"],
        "code": r["code"],
        "quarter_label": r["quarter_label"],
        "window_start": r["window_start"],
        "window_end": r["window_end"],
        "earn_multiplier_bps": r["earn_multiplier_bps"],
        "bonus_cap_cents": r["bonus_cap_cents"],
    })
    return out


def transfer_partner_out(r):
    out = _common(r)
    out.update({
        "name": r["name"],
        "partner_type": r["partner_type"],
        "transfer_ratio_num": r["transfer_ratio_num"],
        "transfer_ratio_den": r["transfer_ratio_den"],
        "min_transfer_points": r["min_transfer_points"],
        "status": r["status"],
    })
    return out


def account_out(r):
    out = _common(r)
    out.update({
        "card_product_id": r["card_product_id"],
        "cardholder_name": r["cardholder_name"],
        "opened_at": r["opened_at"],
        "points_balance": r["points_balance"],
        "pending_points": r["pending_points"],
        "qualifying_spend_cents": r["qualifying_spend_cents"],
        "annual_spend_cents": r["annual_spend_cents"],
        "current_tier_index": r["current_tier_index"],
        "signup_bonus_status": r["signup_bonus_status"],
        "status": r["status"],
    })
    return out


def transaction_out(r):
    out = _common(r)
    out.update({
        "card_account_id": r["card_account_id"],
        "amount_cents": r["amount_cents"],
        "category_code": r["category_code"],
        "transacted_at": r["transacted_at"],
        "earned_points": r["earned_points"],
        "quarterly_bonus_applied_cents": r["quarterly_bonus_applied_cents"],
        "status": r["status"],
    })
    return out


def points_lot_out(r):
    # PointsLot carries only id + created_at (no updated_at / version) per PRD §2.4.
    out = _common(r, with_version=False)
    out.update({
        "card_account_id": r["card_account_id"],
        "source_transaction_id": r["source_transaction_id"],
        "lot_type": r["lot_type"],
        "original_points": r["original_points"],
        "remaining_points": r["remaining_points"],
        "expires_at": r["expires_at"],
        "status": r["status"],
    })
    return out


def redemption_out(r):
    out = _common(r)
    out.update({
        "card_account_id": r["card_account_id"],
        "redemption_type": r["redemption_type"],
        "points_requested": r["points_requested"],
        "transfer_partner_id": r["transfer_partner_id"],
        "expected_card_account_version": r["expected_card_account_version"],
        "redeemed_value": r["redeemed_value"],
        "lots_consumed": r["lots_consumed"],
        "status": r["status"],
    })
    return out


def category_activation_out(r):
    out = _common(r)
    out.update({
        "card_account_id": r["card_account_id"],
        "quarterly_category_id": r["quarterly_category_id"],
        "activated_at": r["activated_at"],
        "status": r["status"],
    })
    return out
