"""Succession, wind-down, rebalance, and pool validation gate tests (corner queue)."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    fixtures, factories,
)
from test_helpers.fixtures import (
    SPONSOR_ADMIN, COMPLIANCE, CONTRIB_ADMIN, advisor_headers, officer_headers,
)


# ===========================================================================
# Pool creation validations
# ===========================================================================
def test_pool_create_nonpositive_nav_rejected(api):
    """PRD 3.1: "A pool's `nav_per_unit_cents` must be greater than zero; a non-positive NAV is rejected at creation with `ERR_POOL_NAV_INVALID`."

    Design: Corner/validations/pool_create_nonpositive_nav_rejected
    """
    sponsor = fixtures.create_sponsor()
    validate_error(api.create_pool(
        factories.create_pool_payload(sponsor["id"], nav_per_unit_cents=0), SPONSOR_ADMIN),
        ApiErrorId.ERR_POOL_NAV_INVALID.value)


# ===========================================================================
# Rebalance validations
# ===========================================================================
def test_rebalance_buy_into_closed_pool_rejected(api):
    """PRD 3.4: "When a target pool is named, that pool must be `OPEN`; buying into a `CLOSED` pool is rejected with `ERR_POOL_CLOSED`."

    Design: Corner/validations/rebalance_buy_into_closed_pool_rejected
    """
    sponsor = fixtures.create_sponsor()
    pool = fixtures.create_pool(sponsor["id"], nav_per_unit_cents=2500, fee_bps=50)
    account = fixtures.create_account(sponsor["id"], "adv-v7")
    fixtures.fund_account_with_cash(account["id"], 100000, "adv-v7")
    order = get_success_data(api.create_rebalance_order(
        factories.create_rebalance_order_payload(account["id"], 50000, target_pool_id=pool["id"], target_pct_bps=5000),
        advisor_headers("adv-v7")))
    get_success_data(api.close_pool(pool["id"], SPONSOR_ADMIN))
    validate_error(api.execute_rebalance_order(order["id"], advisor_headers("adv-v7")),
                   ApiErrorId.ERR_POOL_CLOSED.value)


def test_rebalance_buy_insufficient_cash_rejected(api):
    """PRD 3.4: "For a buy (no source pool), the account's `cash_balance_cents` must be at least the `amount_cents`; insufficient cash is rejected with `ERR_INSUFFICIENT_CASH`."

    Design: Corner/validations/rebalance_buy_insufficient_cash_rejected
    """
    sponsor = fixtures.create_sponsor()
    pool = fixtures.create_pool(sponsor["id"], nav_per_unit_cents=2500, fee_bps=50)
    account = fixtures.create_account(sponsor["id"], "adv-v8")
    fixtures.fund_account_with_cash(account["id"], 50000, "adv-v8")
    order = get_success_data(api.create_rebalance_order(
        factories.create_rebalance_order_payload(account["id"], 60000, target_pool_id=pool["id"], target_pct_bps=5000),
        advisor_headers("adv-v8")))
    validate_error(api.execute_rebalance_order(order["id"], advisor_headers("adv-v8")),
                   ApiErrorId.ERR_INSUFFICIENT_CASH.value)


def test_rebalance_redeem_insufficient_pool_units_rejected(api):
    """PRD 3.4: "For a redeem (a source pool is named), the source allocation's invested value must be at least the `amount_cents`; an under-funded redemption is rejected with `ERR_INSUFFICIENT_POOL_UNITS`."

    Design: Corner/validations/rebalance_redeem_insufficient_pool_units_rejected
    """
    sponsor = fixtures.create_sponsor()
    pool = fixtures.create_pool(sponsor["id"], nav_per_unit_cents=2500, fee_bps=50)
    account = fixtures.create_account(sponsor["id"], "adv-v9")
    fixtures.fund_account_with_cash(account["id"], 50000, "adv-v9")
    fixtures.buy_into_pool(account["id"], pool["id"], 50000, "adv-v9", target_pct_bps=5000)
    redeem = get_success_data(api.create_rebalance_order(
        factories.create_rebalance_order_payload(account["id"], 60000, source_pool_id=pool["id"]),
        advisor_headers("adv-v9")))
    validate_error(api.execute_rebalance_order(redeem["id"], advisor_headers("adv-v9")),
                   ApiErrorId.ERR_INSUFFICIENT_POOL_UNITS.value)


# ===========================================================================
# Succession plan validations
# ===========================================================================
def test_succession_share_bps_not_100_rejected(api):
    """PRD 3.8: "For a `LEGACY_GRANTS` plan the beneficiaries' `share_bps` must sum to exactly 10,000 (a full 100%); any other total is rejected with `ERR_SHARE_BPS_NOT_100`."

    Design: Corner/validations/succession_share_bps_not_100_rejected
    """
    sponsor = fixtures.create_sponsor()
    charity = fixtures.create_vetted_charity(sponsor["id"])
    account = fixtures.create_account(sponsor["id"], "adv-v6")
    validate_error(api.create_succession_plan(
        factories.create_succession_plan_payload(
            account["id"], "LEGACY_GRANTS", [{"charity_id": charity["id"], "share_bps": 9000}]),
        advisor_headers("adv-v6")),
        ApiErrorId.ERR_SHARE_BPS_NOT_100.value)


def test_wind_down_without_confirmed_succession_rejected(api):
    """PRD 3.8: "Wind-down is permitted from `ACTIVE` or `INACTIVE`, and requires that a `CONFIRMED` `LEGACY_GRANTS` succession plan already exist for the account; without one, the request is rejected with `ERR_NO_CONFIRMED_SUCCESSION`."

    Design: Corner/validations/wind_down_without_confirmed_succession_rejected
    """
    sponsor = fixtures.create_sponsor()
    charity = fixtures.create_vetted_charity(sponsor["id"])
    account = fixtures.create_account(sponsor["id"], "adv-v12")
    # Only a DRAFT (not confirmed) plan exists.
    get_success_data(api.create_succession_plan(
        factories.create_succession_plan_payload(
            account["id"], "LEGACY_GRANTS", [{"charity_id": charity["id"], "share_bps": 10000}]),
        advisor_headers("adv-v12")))
    validate_error(api.wind_down_account(account["id"], SPONSOR_ADMIN),
                   ApiErrorId.ERR_NO_CONFIRMED_SUCCESSION.value)
    refreshed = get_success_data(api.get_account(account["id"], SPONSOR_ADMIN))
    assert refreshed["status"] == "ACTIVE"


# ===========================================================================
# execute-succession gates
# ===========================================================================
def test_execute_succession_pending_grants_block_close(api):
    """PRD 3.8: "that no grant remains in `SUBMITTED`, `APPROVED`, or `SCHEDULED` — outstanding grants block the close with `ERR_PENDING_GRANTS_BLOCK_CLOSE"

    Design: Corner/validations/execute_succession_with_pending_grants_rejected
    """
    sponsor, charity, account = fixtures.setup_funded_account_with_vetted_charity(
        cash_amount_cents=1000000, advisor_user_id="adv-v13")
    fixtures.submit_grant(account["id"], charity["id"], 100000, "adv-v13")
    fixtures.create_confirmed_legacy_plan(
        account["id"], [{"charity_id": charity["id"], "share_bps": 10000}], "adv-v13")
    get_success_data(api.wind_down_account(account["id"], SPONSOR_ADMIN))
    validate_error(api.execute_succession(account["id"], SPONSOR_ADMIN),
                   ApiErrorId.ERR_PENDING_GRANTS_BLOCK_CLOSE.value)
    refreshed = get_success_data(api.get_account(account["id"], SPONSOR_ADMIN))
    assert refreshed["status"] == "WIND_DOWN"


def test_execute_succession_beneficiary_not_vetted(api):
    """PRD 3.8: "and that every charity named as a `LEGACY_GRANTS` beneficiary is currently `VETTED` — an unvetted beneficiary blocks the close with `ERR_SUCCESSION_BENEFICIARY_NOT_VETTED`."

    Design: Corner/validations/execute_succession_beneficiary_not_vetted_rejected
    """
    sponsor = fixtures.create_sponsor()
    charity = fixtures.create_vetted_charity(sponsor["id"])
    account = fixtures.create_account(sponsor["id"], "adv-v14")
    fixtures.fund_account_with_cash(account["id"], 500000, "adv-v14")
    fixtures.create_confirmed_legacy_plan(
        account["id"], [{"charity_id": charity["id"], "share_bps": 10000}], "adv-v14")
    get_success_data(api.wind_down_account(account["id"], SPONSOR_ADMIN))
    # Revoke the beneficiary AFTER plan confirmation and wind-down.
    get_success_data(api.vet_charity(
        charity["id"], factories.vet_decision_payload("REVOKE", vetting_note="revoked post-confirm"),
        COMPLIANCE))
    validate_error(api.execute_succession(account["id"], SPONSOR_ADMIN),
                   ApiErrorId.ERR_SUCCESSION_BENEFICIARY_NOT_VETTED.value)
    refreshed = get_success_data(api.get_account(account["id"], SPONSOR_ADMIN))
    assert refreshed["status"] == "WIND_DOWN"


def test_execute_succession_account_not_in_wind_down(api):
    """PRD 3.8: "Execution requires that the account be in `WIND_DOWN` — calling it on an account in any other state is rejected with `ERR_ACCOUNT_NOT_IN_WIND_DOWN"

    Design: Corner/validations/execute_succession_account_not_in_wind_down_rejected
    """
    sponsor = fixtures.create_sponsor()
    account = fixtures.create_account(sponsor["id"], "adv-v15")
    validate_error(api.execute_succession(account["id"], SPONSOR_ADMIN),
                   ApiErrorId.ERR_ACCOUNT_NOT_IN_WIND_DOWN.value)
