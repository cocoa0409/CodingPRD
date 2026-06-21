"""Asset configuration immutability, spot-price patch, and pagination."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS, make_trader_headers, assert_asset_config,
    ApiErrorId, btc_asset_payload,
    set_clock, create_account_at_tier, create_btc_asset,
    create_and_credit_deposit, add_and_activate_address, get_account_version,
    submit_withdrawal,
)

OP = TEST_USERS["operator_headers"]


# ===========================================================================
# Corner / entities — AssetConfig immutability (no version field)
# ===========================================================================
def test_assetconfig_create_has_no_version_and_spot_patchable(api):
    """PRD §2.4: "The `AssetConfig` entity is immutable configuration except for its
    one mutable price field, and the `Trade` entity is an append-only execution
    record; for both of these, `updated_at` and `version` are absent."
    PRD §3.3: "The spot price feeds notional valuation, the travel-rule threshold,
    and thirty-day volume; it is the one mutable field of an asset configuration and
    may be updated in place by an `Operator`."

    Design: Corner/entities/assetconfig_immutable_no_version_field
    """
    created = validate_success(api.create_asset(btc_asset_payload(), OP), 201)
    assert "id" in created and "created_at" in created
    assert "version" not in created, "AssetConfig must not carry a version field"
    assert_asset_config(created)
    patched = validate_success(api.patch_asset(created["id"],
                                               {"spot_price_usd": 41000}, OP))
    assert patched["spot_price_usd"] == 41000


# ===========================================================================
# Corner / endpoints — pagination out-of-range
# ===========================================================================
def test_pagination_limit_over_max_rejected(api):
    """PRD §2.3: "A `limit` outside the range 1 to 100, or an out-of-range
    pagination parameter generally, is rejected with `ERR_VALIDATION`."

    Design: Corner/endpoints/pagination_limit_over_max_rejected
    """
    resp = api.list_accounts(OP, params={"limit": 101})
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ===========================================================================
# Corner / endpoints — spot price patch recomputes withdrawal notional
# ===========================================================================
def test_spot_price_patch_recomputes_notional_and_travel_rule(api):
    """PRD §3.6: "At submission, the system computes `notional_usd` as the requested
    `amount` multiplied by the asset's `spot_price_usd`, and sets
    `requires_travel_rule` to true when that notional is at least the travel-rule
    threshold of 3,000 USD and false otherwise."

    Design: Corner/endpoints/spot_price_patch_recomputes_notional
    """
    set_clock("2027-12-01T00:00:00Z")
    btc = create_btc_asset()
    acc = create_account_at_tier("TIER_2", email="pp@x.com", full_name="PP")
    acc_id = acc["id"]
    create_and_credit_deposit(acc_id, "BTC", 1.0, 30000, required_confirmations=1)
    addr = add_and_activate_address(acc_id, "BTC", chain_address="0xPP",
                                    activate_clock="2027-12-02T01:00:00Z")
    # raise spot 40000 -> 80000
    validate_success(api.patch_asset(btc["id"], {"spot_price_usd": 80000}, OP))
    # 0.05 BTC at new spot 80000 -> notional 4000 (>= 3000)
    wd = submit_withdrawal(acc_id, addr["id"], 0.05)
    assert wd["notional_usd"] == 4000
    assert wd["requires_travel_rule"] is True
