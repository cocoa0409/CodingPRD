"""Convert internal records to the JSON shapes returned by the API."""
from clock import to_iso
from numeric import to_number


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": to_iso(rec["created_at"]),
        "updated_at": to_iso(rec["updated_at"]),
        "version": rec["version"],
    }


def _config_common(rec):
    return {"id": rec["id"], "created_at": to_iso(rec["created_at"])}


def account_out(rec, store):
    from services.fees import maker_volume_30d, taker_volume_30d, fee_tier_for
    maker_vol = maker_volume_30d(store, rec["id"])
    taker_vol = taker_volume_30d(store, rec["id"])
    out = _common(rec)
    out.update({
        "email": rec["email"],
        "full_name": rec["full_name"],
        "residence_country": rec["residence_country"],
        "kyc_tier": rec["kyc_tier"],
        "kyc_status": rec["kyc_status"],
        "pending_tier": rec.get("pending_tier"),
        "account_status": rec["account_status"],
        "maker_volume_30d_usd": to_number(maker_vol),
        "taker_volume_30d_usd": to_number(taker_vol),
        "fee_tier": fee_tier_for(store, taker_vol),
        "cost_basis_method": rec["cost_basis_method"],
    })
    return out


def asset_out(rec):
    out = _config_common(rec)
    out.update({
        "symbol": rec["symbol"],
        "decimals": rec["decimals"],
        "required_confirmations": rec["required_confirmations"],
        "is_fiat": rec["is_fiat"],
        "min_withdrawal_amount": to_number(rec["min_withdrawal_amount"]),
        "network_fee": to_number(rec["network_fee"]),
        "spot_price_usd": to_number(rec["spot_price_usd"]),
    })
    return out


def fee_schedule_out(rec):
    out = _config_common(rec)
    out.update({
        "tier_name": rec["tier_name"],
        "min_taker_volume_30d_usd": to_number(rec["min_taker_volume_30d_usd"]),
        "maker_fee_bps": to_number(rec["maker_fee_bps"]),
        "taker_fee_bps": to_number(rec["taker_fee_bps"]),
    })
    return out


def balance_out(rec):
    from numeric import D
    avail = D(rec["available_raw"])
    reserved = D(rec["reserved_raw"])
    held = D(rec["held_raw"])
    total = avail + reserved + held
    out = _common(rec)
    out.update({
        "account_id": rec["account_id"],
        "asset": rec["asset"],
        "total_amount": to_number(total),
        "reserved_amount": to_number(reserved),
        "held_amount": to_number(held),
        "available_amount": to_number(avail),
    })
    return out


def withdrawal_address_out(rec):
    out = _common(rec)
    out.update({
        "account_id": rec["account_id"],
        "asset": rec["asset"],
        "chain_address": rec["chain_address"],
        "label": rec["label"],
        "status": rec["status"],
        "activates_at": to_iso(rec["activates_at"]),
    })
    return out


def deposit_out(rec):
    out = _common(rec)
    out.update({
        "account_id": rec["account_id"],
        "asset": rec["asset"],
        "amount": to_number(rec["amount"]),
        "confirmations": rec["confirmations"],
        "unit_cost_usd": to_number(rec["unit_cost_usd"]),
        "status": rec["status"],
    })
    return out


def withdrawal_out(rec):
    out = _common(rec)
    out.update({
        "account_id": rec["account_id"],
        "withdrawal_address_id": rec["withdrawal_address_id"],
        "asset": rec["asset"],
        "amount": to_number(rec["amount"]),
        "notional_usd": to_number(rec["notional_usd"]),
        "requires_travel_rule": rec["requires_travel_rule"],
        "replaces_withdrawal_id": rec.get("replaces_withdrawal_id"),
        "status": rec["status"],
    })
    return out


def travel_rule_record_out(rec):
    out = _common(rec)
    out.update({
        "withdrawal_id": rec["withdrawal_id"],
        "originator_name": rec["originator_name"],
        "beneficiary_name": rec["beneficiary_name"],
        "beneficiary_vasp": rec["beneficiary_vasp"],
        "filed_by_user_id": rec["filed_by_user_id"],
        "status": rec["status"],
    })
    return out


def order_out(rec):
    out = _common(rec)
    out.update({
        "account_id": rec["account_id"],
        "base_asset": rec["base_asset"],
        "quote_asset": rec["quote_asset"],
        "side": rec["side"],
        "order_type": rec["order_type"],
        "limit_price": to_number(rec["limit_price"]) if rec.get("limit_price") is not None else None,
        "quantity": to_number(rec["quantity"]),
        "filled_quantity": to_number(rec["filled_quantity"]),
        "avg_fill_price": to_number(rec["avg_fill_price"]) if rec.get("avg_fill_price") is not None else None,
        "reserved_remaining": to_number(rec["reserved_remaining"]),
        "lifecycle_status": rec["lifecycle_status"],
        "time_in_force": rec["time_in_force"],
    })
    return out


def trade_out(rec):
    out = _config_common(rec)
    out.update({
        "maker_order_id": rec["maker_order_id"],
        "taker_order_id": rec["taker_order_id"],
        "base_asset": rec["base_asset"],
        "quote_asset": rec["quote_asset"],
        "price": to_number(rec["price"]),
        "quantity": to_number(rec["quantity"]),
        "notional_usd": to_number(rec["notional_usd"]),
        "maker_fee": to_number(rec["maker_fee"]),
        "taker_fee": to_number(rec["taker_fee"]),
        "executed_at": to_iso(rec["executed_at"]),
    })
    return out


def cost_basis_lot_out(rec):
    out = _common(rec)
    out.update({
        "account_id": rec["account_id"],
        "asset": rec["asset"],
        "origin_type": rec["origin_type"],
        "origin_id": rec["origin_id"],
        "acquired_at": to_iso(rec["acquired_at"]),
        "original_quantity": to_number(rec["original_quantity"]),
        "remaining_quantity": to_number(rec["remaining_quantity"]),
        "unit_cost_usd": to_number(rec["unit_cost_usd"]),
        "status": rec["status"],
    })
    return out


def staking_position_out(rec):
    out = _common(rec)
    out.update({
        "account_id": rec["account_id"],
        "asset": rec["asset"],
        "principal_amount": to_number(rec["principal_amount"]),
        "apr_bps": to_number(rec["apr_bps"]),
        "accrued_rewards": to_number(rec["accrued_rewards"]),
        "last_accrual_at": to_iso(rec["last_accrual_at"]),
        "status": rec["status"],
        "unbond_started_at": to_iso(rec["unbond_started_at"]) if rec.get("unbond_started_at") else None,
        "unbond_available_at": to_iso(rec["unbond_available_at"]) if rec.get("unbond_available_at") else None,
    })
    return out
