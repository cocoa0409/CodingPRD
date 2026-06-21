"""Transitive cascade tests: grant payout chain (redeem -> ledger -> balance -> inactivity)
and charity revoke -> scheduled-grant cancellation -> balance recompute.
"""
from test_helpers import (
    validate_success, get_success_data, fixtures, factories,
)
from test_helpers.fixtures import (
    SPONSOR_ADMIN, COMPLIANCE, CONTRIB_ADMIN, advisor_headers, officer_headers,
)


# ===========================================================================
# Cascade depth>=3: grant pay -> redeem -> ledger + balance -> inactivity clear
# ===========================================================================
def test_grant_pay_redeems_pool_and_appends_ledger(api):
    """PRD 3.6: "The payout cascade appends, for each pool drawn down, a `LedgerEntry` of `entry_type` `POOL_REDEEM`, and one `LedgerEntry` of `entry_type` `GRANT_PAID` with `signed_amount_cents` equal to the negative `amount_cents`."

    Design: Difficulty/transitive_cascade/grant_pay_redeem_ledger_inactivity_cascade
    """
    sponsor = fixtures.create_sponsor(inactivity_quarters=8)
    pool = fixtures.create_pool(sponsor["id"], nav_per_unit_cents=2500, fee_bps=50, risk_tier="GROWTH")
    charity = fixtures.create_vetted_charity(sponsor["id"])
    account = fixtures.create_account(sponsor["id"], "adv-6")
    fixtures.fund_account_with_cash(account["id"], 130000, "adv-6")
    fixtures.buy_into_pool(account["id"], pool["id"], 100000, "adv-6", target_pct_bps=6000)
    # cash now 30000, invested 100000 (units 40000000)
    grant = fixtures.create_scheduled_grant(
        account["id"], charity["id"], 100000, "adv-6", officer_user_id="officer-2")
    # Close the quarter so the account becomes INACTIVE (never paid, grantable > 0).
    validate_success(api.close_quarter(sponsor["id"], SPONSOR_ADMIN))
    inactive = get_success_data(api.get_account(account["id"], SPONSOR_ADMIN))
    assert inactive["status"] == "INACTIVE"

    paid = validate_success(api.pay_grant(grant["id"], officer_headers("officer-2")))
    assert paid["status"] == "PAID"

    redeems = get_success_data(api.list_ledger_entries(
        SPONSOR_ADMIN, params={"donor_account_id": account["id"], "entry_type": "POOL_REDEEM"}))
    grant_paid = get_success_data(api.list_ledger_entries(
        SPONSOR_ADMIN, params={"donor_account_id": account["id"], "entry_type": "GRANT_PAID"}))
    assert len(redeems) >= 1
    assert len(grant_paid) == 1
    assert grant_paid[0]["signed_amount_cents"] == -100000

    allocs = get_success_data(api.list_allocations(
        advisor_headers("adv-6"), params={"donor_account_id": account["id"]}))
    # need 70000 from invested -> redeem ceil(70000*1e6/2500)=28000000 -> 40000000-28000000=12000000
    assert allocs[0]["units_micro"] == 12000000


def test_grant_pay_clears_inactivity_to_active(api):
    """PRD 3.6: "The grant's `paid_quarter_index` is set to the sponsor's `current_quarter_index`, and the account's `last_grant_paid_quarter` is updated to the same value — recording that a paid grant occurred this quarter clears the inactivity countdown. If the account was `INACTIVE`, paying a grant transitions it back to `ACTIVE`."

    Design: Difficulty/transitive_cascade/grant_pay_redeem_ledger_inactivity_cascade
    """
    sponsor = fixtures.create_sponsor(inactivity_quarters=8)
    pool = fixtures.create_pool(sponsor["id"], nav_per_unit_cents=2500, fee_bps=50, risk_tier="GROWTH")
    charity = fixtures.create_vetted_charity(sponsor["id"])
    account = fixtures.create_account(sponsor["id"], "adv-6b")
    fixtures.fund_account_with_cash(account["id"], 130000, "adv-6b")
    fixtures.buy_into_pool(account["id"], pool["id"], 100000, "adv-6b", target_pct_bps=6000)
    grant = fixtures.create_scheduled_grant(
        account["id"], charity["id"], 100000, "adv-6b", officer_user_id="officer-2b")
    validate_success(api.close_quarter(sponsor["id"], SPONSOR_ADMIN))
    assert get_success_data(api.get_account(account["id"], SPONSOR_ADMIN))["status"] == "INACTIVE"

    validate_success(api.pay_grant(grant["id"], officer_headers("officer-2b")))
    acct = get_success_data(api.get_account(account["id"], SPONSOR_ADMIN))
    assert acct["status"] == "ACTIVE"
    assert acct["cash_balance_cents"] == 0
    assert acct["invested_value_cents"] == 30000


# ===========================================================================
# Cascade depth>=2: charity REVOKE -> scheduled grant CANCELLED -> balance recompute
# ===========================================================================
def test_charity_revoke_cancels_scheduled_grant(api):
    """PRD 3.2: "A **REVOKE** decision moves a charity from `VETTED` to `REVOKED`, or from `WATCHLISTED` to `REVOKED`, setting `status` to `REVOKED`. Revocation cascades: every grant recommendation in `SCHEDULED` status that references this charity is transitioned to `CANCELLED`, and on each affected account the committed amount is released by recomputing `committed_grants_cents` and then `grantable_balance_cents`."

    Design: Difficulty/transitive_cascade/charity_revoke_grant_cancel_balance_recompute_cascade
    """
    sponsor, charity, account = fixtures.setup_funded_account_with_vetted_charity(
        cash_amount_cents=1000000, advisor_user_id="adv-7")
    grant = fixtures.create_scheduled_grant(
        account["id"], charity["id"], 200000, "adv-7", officer_user_id="officer-3")

    revoked = validate_success(api.vet_charity(
        charity["id"], factories.vet_decision_payload("REVOKE", vetting_note="lost 501c3"),
        COMPLIANCE))
    assert revoked["status"] == "REVOKED"

    refreshed_grant = get_success_data(api.get_grant(grant["id"], SPONSOR_ADMIN))
    assert refreshed_grant["status"] == "CANCELLED"


def test_charity_revoke_releases_committed_balance(api):
    """PRD 3.2: "on each affected account the committed amount is released by recomputing `committed_grants_cents` and then `grantable_balance_cents`."

    Design: Difficulty/transitive_cascade/charity_revoke_grant_cancel_balance_recompute_cascade
    """
    sponsor, charity, account = fixtures.setup_funded_account_with_vetted_charity(
        cash_amount_cents=1000000, advisor_user_id="adv-7b")
    fixtures.create_scheduled_grant(
        account["id"], charity["id"], 200000, "adv-7b", officer_user_id="officer-3b")
    committed_before = get_success_data(api.get_account(account["id"], SPONSOR_ADMIN))["committed_grants_cents"]
    assert committed_before == 200000

    validate_success(api.vet_charity(
        charity["id"], factories.vet_decision_payload("REVOKE", vetting_note="revoked"),
        COMPLIANCE))
    acct = get_success_data(api.get_account(account["id"], SPONSOR_ADMIN))
    assert acct["committed_grants_cents"] == 0
    assert acct["grantable_balance_cents"] == 1000000


# Note: corner stubs grant_pay_cross_entity_inactive_clears_to_active and
# charity_revoke_cascade_cancels_scheduled_grants are excluded_because their assertions are
# owned by the two difficulty instances above; their cross-references resolve, so no placeholder
# tests are emitted (per the design-index-only contract).
