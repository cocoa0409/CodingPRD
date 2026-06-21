"""RBAC enforcement, optimistic concurrency on change-plan, version monotonicity,
and immediate MRR visibility.

Queue B (corner) translations for the rbac, cross_cutting_complexity_layers,
and consistency_model sections. The derived_mrr_reconciles_after_addon_then_cancel
instance is an excluded_because stub — owned by the compensating_invariant
difficulty instance — and is not translated here.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    make_account_owner_headers,
    TEST_USERS,
    create_plan_payload,
    create_subscription_payload,
    change_plan_payload,
    add_addon_payload,
    setup_active_subscription,
    setup_jurisdiction_and_clock,
    create_plan,
    create_account,
    create_addon,
    set_clock,
)

ADMIN = TEST_USERS["billing_admin_headers"]


def _owner(account_id):
    return make_account_owner_headers(account_id)


# ─── rbac ─────────────────────────────────────────────
def test_account_owner_cannot_create_plan(api):
    """PRD §2.1: "A request that is well-authenticated but whose role is not permitted to perform the requested operation is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/account_owner_cannot_create_plan
    """
    setup_jurisdiction_and_clock()
    account = create_account(email="rb1@x.com")
    res = api.create_plan(
        create_plan_payload(tier="BASIC", monthly_fee_cents=3000), _owner(account["id"])
    )
    validate_error(res, "ERR_UNAUTHORIZED")


def test_account_owner_cannot_act_on_other_accounts_subscription(api):
    """PRD §2.1: "an `AccountOwner` may act only on their own account and on subscriptions, invoices, lines, payments, usage records, revenue entries, add-ons, and pause windows that resolve back to that account; an attempt to read or mutate another account's resources is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/account_owner_cannot_act_on_other_accounts_subscription
    """
    plan, account_b, sub_b = setup_active_subscription(plan_tier="BASIC", email="ownerB@x.com")
    account_a = create_account(email="ownerA@x.com")
    # Account A (X-User-ID = A.id) tries to cancel account B's subscription.
    res = api.cancel_subscription(account_b["id"], sub_b["id"], _owner(account_a["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")


def test_missing_auth_header_returns_unauthenticated(api):
    """PRD §2.1: "A request whose `X-User-Role` is missing or malformed — or, for any role other than `Anonymous`, whose `X-User-ID` is missing or malformed — is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_header_returns_unauthenticated
    """
    res = api.get_mrr_report(headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")


# ─── cross-cutting: optimistic concurrency ────────────
def test_stale_subscription_version_on_change_plan_rejected(api):
    """PRD §2.6: "If that value does not match the subscription's current `version` — because another change-plan write has since advanced the subscription, legitimately superseding the prior effective plan and rewriting the proration basis — the request is rejected with `ERR_STALE_VERSION` and HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_subscription_version_on_change_plan
    """
    basic, account, sub = setup_active_subscription(plan_tier="BASIC", email="occ@x.com")
    pro = create_plan(tier="PRO", monthly_fee_cents=9000, trial_days=14)
    ent = create_plan(tier="ENTERPRISE", monthly_fee_cents=20000, trial_days=14)
    set_clock("2026-06-11T00:00:00Z")
    sub_v0 = validate_success(api.get_subscription(sub["id"], _owner(account["id"])), 200)["version"]
    # First change-plan with the fresh version succeeds and advances version.
    validate_success(
        api.change_plan(
            account["id"], sub["id"], change_plan_payload(pro["id"], sub_v0), _owner(account["id"])
        ),
        200,
    )
    # Second change-plan still carrying the pre-bump version is stale.
    res = api.change_plan(
        account["id"], sub["id"], change_plan_payload(ent["id"], sub_v0), _owner(account["id"])
    )
    validate_error(res, "ERR_STALE_VERSION")


def test_stale_change_plan_does_not_take_effect(api):
    """PRD §2.6: "This prevents a client from prorating against a stale basis and
    overwriting a plan change it never saw."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_subscription_version_on_change_plan
    """
    basic, account, sub = setup_active_subscription(plan_tier="BASIC", email="occ2@x.com")
    pro = create_plan(tier="PRO", monthly_fee_cents=9000, trial_days=14)
    ent = create_plan(tier="ENTERPRISE", monthly_fee_cents=20000, trial_days=14)
    set_clock("2026-06-11T00:00:00Z")
    sub_v0 = validate_success(api.get_subscription(sub["id"], _owner(account["id"])), 200)["version"]
    validate_success(
        api.change_plan(
            account["id"], sub["id"], change_plan_payload(pro["id"], sub_v0), _owner(account["id"])
        ),
        200,
    )
    validate_error(
        api.change_plan(
            account["id"], sub["id"], change_plan_payload(ent["id"], sub_v0), _owner(account["id"])
        ),
        "ERR_STALE_VERSION",
    )
    after = validate_success(api.get_subscription(sub["id"], _owner(account["id"])), 200)
    assert after["plan_id"] == pro["id"], (
        f"stale change must not take effect; plan_id should stay PRO, got {after['plan_id']}"
    )


def test_subscription_version_increments_on_mutation(api):
    """PRD §2.4: "The `version` is an integer that begins at its initial value and increments by one with each mutation".

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_mutation
    """
    plan, account, sub = setup_active_subscription(plan_tier="BASIC", email="ver@x.com")
    seats = create_addon(code="SEATS", monthly_fee_cents=2000)
    v0 = sub["version"]
    validate_success(
        api.add_subscription_addon(
            account["id"], sub["id"], add_addon_payload(seats["id"]), _owner(account["id"])
        ),
        201,
    )
    after = validate_success(api.get_subscription(sub["id"], _owner(account["id"])), 200)
    assert after["version"] > v0, (
        f"version after add-on attach ({after['version']}) must exceed create version ({v0})"
    )


# ─── consistency model ────────────────────────────────
def test_mrr_visible_immediately_after_active_create(api):
    """PRD §2.9: "Both are recomputed — never left stale — whenever an event could change
    them: creating, converting, or canceling a subscription". PRD §3.2: "recomputes `mrr_contribution_cents`, and bubbles the change up into the account's `mrr_cents`."

    Design: Corner/consistency_model/immediate_visibility_of_mrr_on_create_response
    """
    plan, account, sub = setup_active_subscription(
        plan_fee_cents=9000, plan_tier="PRO", email="imv@x.com"
    )
    acct = validate_success(api.get_account(account["id"], _owner(account["id"])), 200)
    assert acct["mrr_cents"] == 9000, f"mrr should reflect new ACTIVE subscription, got {acct['mrr_cents']}"
