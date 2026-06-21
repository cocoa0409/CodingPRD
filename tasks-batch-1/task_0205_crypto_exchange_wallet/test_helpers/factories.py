"""Payload factories — one per entity, input fields only (PRD §3, §4)."""


# --- Account (PRD §3.1) -------------------------------------------------------
def create_account_payload(**overrides) -> dict:
    """email, full_name, residence_country required; cost_basis_method optional."""
    defaults = {
        "email": "trader@example.com",
        "full_name": "Test Trader",
        "residence_country": "US",
    }
    defaults.update(overrides)
    return defaults


def kyc_application_payload(requested_tier, **overrides) -> dict:
    defaults = {"requested_tier": requested_tier}
    defaults.update(overrides)
    return defaults


def kyc_decision_payload(decision, **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


# --- AssetConfig (PRD §3.3) ---------------------------------------------------
def create_asset_payload(symbol, decimals, required_confirmations,
                         min_withdrawal_amount, network_fee, spot_price_usd,
                         is_fiat=False, **overrides) -> dict:
    defaults = {
        "symbol": symbol,
        "decimals": decimals,
        "required_confirmations": required_confirmations,
        "is_fiat": is_fiat,
        "min_withdrawal_amount": min_withdrawal_amount,
        "network_fee": network_fee,
        "spot_price_usd": spot_price_usd,
    }
    defaults.update(overrides)
    return defaults


def usd_asset_payload(**overrides) -> dict:
    defaults = dict(
        symbol="USD", decimals=2, required_confirmations=0, is_fiat=True,
        min_withdrawal_amount=1, network_fee=0, spot_price_usd=1,
    )
    defaults.update(overrides)
    return create_asset_payload(**defaults)


def btc_asset_payload(**overrides) -> dict:
    defaults = dict(
        symbol="BTC", decimals=8, required_confirmations=1, is_fiat=False,
        min_withdrawal_amount=0.0001, network_fee=0.0001, spot_price_usd=40000,
    )
    defaults.update(overrides)
    return create_asset_payload(**defaults)


def eth_asset_payload(**overrides) -> dict:
    defaults = dict(
        symbol="ETH", decimals=8, required_confirmations=1, is_fiat=False,
        min_withdrawal_amount=0.001, network_fee=0.001, spot_price_usd=2000,
    )
    defaults.update(overrides)
    return create_asset_payload(**defaults)


# --- FeeSchedule (PRD §3.3) ---------------------------------------------------
def create_fee_schedule_payload(tier_name, min_taker_volume_30d_usd,
                                maker_fee_bps, taker_fee_bps, **overrides) -> dict:
    defaults = {
        "tier_name": tier_name,
        "min_taker_volume_30d_usd": min_taker_volume_30d_usd,
        "maker_fee_bps": maker_fee_bps,
        "taker_fee_bps": taker_fee_bps,
    }
    defaults.update(overrides)
    return defaults


def tier_base_fee_schedule_payload(**overrides) -> dict:
    return create_fee_schedule_payload(
        tier_name="TIER_BASE", min_taker_volume_30d_usd=0,
        maker_fee_bps=10, taker_fee_bps=30, **overrides
    )


# --- Deposit (PRD §3.4) -------------------------------------------------------
def create_deposit_payload(account_id, asset, amount, unit_cost_usd, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "asset": asset,
        "amount": amount,
        "unit_cost_usd": unit_cost_usd,
    }
    defaults.update(overrides)
    return defaults


def confirmations_payload(delta, **overrides) -> dict:
    defaults = {"delta": delta}
    defaults.update(overrides)
    return defaults


# --- WithdrawalAddress (PRD §3.5) ---------------------------------------------
def create_withdrawal_address_payload(account_id, asset, chain_address,
                                      label, expected_account_version, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "asset": asset,
        "chain_address": chain_address,
        "label": label,
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


# --- Withdrawal (PRD §3.6) ----------------------------------------------------
def create_withdrawal_payload(account_id, withdrawal_address_id, amount, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "withdrawal_address_id": withdrawal_address_id,
        "amount": amount,
    }
    defaults.update(overrides)
    return defaults


def screen_result_payload(result, **overrides) -> dict:
    defaults = {"result": result}
    defaults.update(overrides)
    return defaults


def travel_rule_record_payload(originator_name="Originator",
                               beneficiary_name="Beneficiary",
                               beneficiary_vasp="VASP-1", **overrides) -> dict:
    defaults = {
        "originator_name": originator_name,
        "beneficiary_name": beneficiary_name,
        "beneficiary_vasp": beneficiary_vasp,
    }
    defaults.update(overrides)
    return defaults


# --- Order (PRD §3.8) ---------------------------------------------------------
def create_order_payload(account_id, base_asset, quote_asset, side, order_type,
                         quantity, expected_account_version,
                         limit_price=None, time_in_force=None, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "base_asset": base_asset,
        "quote_asset": quote_asset,
        "side": side,
        "order_type": order_type,
        "quantity": quantity,
        "expected_account_version": expected_account_version,
    }
    if limit_price is not None:
        defaults["limit_price"] = limit_price
    if time_in_force is not None:
        defaults["time_in_force"] = time_in_force
    defaults.update(overrides)
    return defaults


# --- StakingPosition (PRD §3.11) ----------------------------------------------
def create_staking_position_payload(account_id, asset, principal_amount,
                                    apr_bps, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "asset": asset,
        "principal_amount": principal_amount,
        "apr_bps": apr_bps,
    }
    defaults.update(overrides)
    return defaults
