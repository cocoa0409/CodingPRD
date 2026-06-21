"""Validation precedence (account-active gate beats business rule) and cross-entity
state-dependent business constraints (add-on rank, promo rank).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    create_package,
    create_premium_channel,
    create_promotion_offer,
    create_active_account,
    account_version,
)

ADMIN = TEST_USERS["billing_admin_headers"]
CSA = TEST_USERS["customer_service_agent_headers"]


# ===========================================================================
# priority_pair_validation_conflict / state_beats_business_constraint_on_addon_attach
#
# PRD §2.7 verbatim pins: account-active (ERR_ACCOUNT_NOT_ACTIVE) precedes the
# operation-specific business rule (ERR_ADDON_RANK_TOO_HIGH). A SUSPENDED account
# attaching a too-high-rank premium must surface the account-active error.
# ===========================================================================
def test_suspended_account_too_high_addon_returns_account_not_active(api):
    """PRD §2.7: "then the state check that the target resource is in a state from which the
    requested transition is legal (`ERR_INVALID_STATE`); then the rule that the account's
    lifecycle must be `ACTIVE` for a plan, add-on, equipment, or promotion mutation
    (`ERR_ACCOUNT_NOT_ACTIVE`); then the optimistic-concurrency version check
    (`ERR_STALE_ACCOUNT_VERSION`); and finally the operation-specific business and body-shape
    checks."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_constraint_on_addon_attach
    """
    basic = create_package(tier_code="BASIC", monthly_fee_cents=3000, rank=1, channel_count=60)
    sports = create_premium_channel(code="SPORTS", name="Sports", kind="ADD_ON", monthly_fee_cents=2000, min_package_rank=3)
    account, _ = create_active_account(basic, service_state_code="CA")
    validate_success(api.suspend_account(account["id"], CSA), 200)

    res = api.attach_add_on(account["id"], {"premium_channel_id": sports["id"]}, CSA)
    validate_error(res, "ERR_ACCOUNT_NOT_ACTIVE")


def test_account_active_gate_masks_addon_rank_business_check(api):
    """PRD §2.7: "A check earlier in this order always masks one later in the order, so an
    unauthenticated request is never told it also pointed at a missing account."
    PRD §2.8: "If the account is in any other lifecycle state — `PROSPECT`, `SUSPENDED`, or
    `CANCELLED` — these operations are rejected with `ERR_ACCOUNT_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_constraint_on_addon_attach
    """
    basic = create_package(tier_code="BASIC", monthly_fee_cents=3000, rank=1, channel_count=60)
    sports = create_premium_channel(code="SPORTS2", name="Sports2", kind="ADD_ON", monthly_fee_cents=2000, min_package_rank=3)
    account, _ = create_active_account(basic, service_state_code="CA")
    validate_success(api.suspend_account(account["id"], CSA), 200)

    res = api.attach_add_on(account["id"], {"premium_channel_id": sports["id"]}, CSA)
    # account-active gate (priority over rank business check) -> 409, not the 422 rank error
    validate_error(res, "ERR_ACCOUNT_NOT_ACTIVE", expected_status=409)


# ===========================================================================
# cross_entity_state_dependency / addon_attach_depends_on_subscription_package_rank
# ===========================================================================
def test_attach_addon_above_package_rank_rejected(api):
    """PRD §3.5: "The attach is permitted only when the premium channel's `min_package_rank`
    is less than or equal to the account's current package rank; a channel whose minimum rank
    exceeds the current rank is rejected with `ERR_ADDON_RANK_TOO_HIGH` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/addon_attach_depends_on_subscription_package_rank
    """
    basic = create_package(tier_code="BASIC", monthly_fee_cents=3000, rank=1, channel_count=60)
    sports = create_premium_channel(code="SPORTS", name="Sports", kind="ADD_ON", monthly_fee_cents=2000, min_package_rank=3)
    account, _ = create_active_account(basic, service_state_code="CA")

    res = api.attach_add_on(account["id"], {"premium_channel_id": sports["id"]}, CSA)
    validate_error(res, "ERR_ADDON_RANK_TOO_HIGH")


def test_addon_rank_too_high_uses_422(api):
    """PRD §3.5: "a channel whose minimum rank exceeds the current rank is rejected with
    `ERR_ADDON_RANK_TOO_HIGH` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/addon_attach_depends_on_subscription_package_rank
    """
    basic = create_package(tier_code="BASIC", monthly_fee_cents=3000, rank=1, channel_count=60)
    sports = create_premium_channel(code="SPORTSX", name="SportsX", kind="ADD_ON", monthly_fee_cents=2000, min_package_rank=3)
    account, _ = create_active_account(basic, service_state_code="CA")

    res = api.attach_add_on(account["id"], {"premium_channel_id": sports["id"]}, CSA)
    validate_error(res, "ERR_ADDON_RANK_TOO_HIGH", expected_status=422)


# ===========================================================================
# cross_entity_state_dependency / promo_apply_depends_on_subscription_package_rank
# ===========================================================================
def test_apply_promo_above_package_rank_rejected(api):
    """PRD §3.6: "A first application is permitted only when the account is `ACTIVE`, its
    `promo_status` is `NONE`, the referenced offer is active, and the account's current package
    rank is at least the offer's `requires_min_rank`. A current rank below the offer's minimum
    is rejected with `ERR_PROMO_RANK_NOT_MET` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/promo_apply_depends_on_subscription_package_rank
    """
    basic = create_package(tier_code="BASIC", monthly_fee_cents=3000, rank=1, channel_count=60)
    offer = create_promotion_offer(
        code="PREMONLY", discount_kind="PERCENT_OFF_PACKAGE", percent_off=0.1, promo_months=6,
        requires_min_rank=3, rollback_protected=False,
    )
    account, _ = create_active_account(basic, service_state_code="CA")
    v = account_version(account["id"])

    res = api.apply_promotion(
        account["id"], {"promotion_offer_id": offer["id"], "expected_account_version": v}, CSA
    )
    validate_error(res, "ERR_PROMO_RANK_NOT_MET")


def test_promo_rank_not_met_uses_422(api):
    """PRD §3.6: "A current rank below the offer's minimum is rejected with
    `ERR_PROMO_RANK_NOT_MET` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/promo_apply_depends_on_subscription_package_rank
    """
    basic = create_package(tier_code="BASIC", monthly_fee_cents=3000, rank=1, channel_count=60)
    offer = create_promotion_offer(
        code="PREMONLY2", discount_kind="PERCENT_OFF_PACKAGE", percent_off=0.1, promo_months=6,
        requires_min_rank=3, rollback_protected=False,
    )
    account, _ = create_active_account(basic, service_state_code="CA")
    v = account_version(account["id"])

    res = api.apply_promotion(
        account["id"], {"promotion_offer_id": offer["id"], "expected_account_version": v}, CSA
    )
    validate_error(res, "ERR_PROMO_RANK_NOT_MET", expected_status=422)
