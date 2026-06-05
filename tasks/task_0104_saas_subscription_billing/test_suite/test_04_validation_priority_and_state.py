"""Validation-priority conflicts and cross-entity state dependencies.

Queue A (difficulty) translations for:
  priority_pair_validation_conflict (both instances),
  cross_entity_state_dependency (both instances).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    make_account_owner_headers,
    TEST_USERS,
    change_plan_payload,
    create_subscription_payload,
    create_plan_payload,
    NON_EXISTENT_PLAN_ID,
    setup_active_subscription,
    setup_jurisdiction_and_clock,
    create_plan,
    create_coupon,
    create_account,
    archive_plan,
    set_clock,
)

ADMIN = TEST_USERS["billing_admin_headers"]


def _owner(account_id):
    return make_account_owner_headers(account_id)


class TestPriorityStateBeatsArchived:
    """State legality (ERR_INVALID_STATE) outranks the plan-archived business rule."""

    def test_change_plan_on_canceled_sub_to_archived_plan_returns_invalid_state(self, api):
        """PRD §2.7: "Only after all of the above does the system evaluate state-machine legality, returning `ERR_INVALID_STATE` when the target resource is not in a state that permits the requested transition. The remaining domain-specific business rules — described throughout Section 3 — are evaluated after these foundational checks."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_plan_archived_on_change_plan
        """
        basic, account, sub = setup_active_subscription(plan_tier="BASIC", email="pc1@x.com")
        target = create_plan(tier="PRO", monthly_fee_cents=9000, trial_days=14)
        archive_plan(target["id"])
        # Cancel the subscription so the lifecycle state forbids change-plan.
        validate_success(api.cancel_subscription(account["id"], sub["id"], _owner(account["id"])), 200)
        sub_now = validate_success(api.get_subscription(sub["id"], _owner(account["id"])), 200)
        res = api.change_plan(
            account["id"],
            sub["id"],
            change_plan_payload(target["id"], sub_now["version"]),
            _owner(account["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_rejected_change_plan_leaves_canceled_subscription_unchanged(self, api):
        """PRD §2.7: "Only after all of the above does the system evaluate state-machine legality, returning `ERR_INVALID_STATE` when the target resource is not in a state that permits the requested transition." PRD §3.9: "Either way, a subscription not in the originating state for these transitions is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_plan_archived_on_change_plan
        """
        basic, account, sub = setup_active_subscription(plan_tier="BASIC", email="pc1b@x.com")
        target = create_plan(tier="PRO", monthly_fee_cents=9000, trial_days=14)
        archive_plan(target["id"])
        validate_success(api.cancel_subscription(account["id"], sub["id"], _owner(account["id"])), 200)
        sub_now = validate_success(api.get_subscription(sub["id"], _owner(account["id"])), 200)
        validate_error(
            api.change_plan(
                account["id"],
                sub["id"],
                change_plan_payload(target["id"], sub_now["version"]),
                _owner(account["id"]),
            ),
            "ERR_INVALID_STATE",
        )
        after = validate_success(api.get_subscription(sub["id"], _owner(account["id"])), 200)
        assert after["lifecycle_status"] == "CANCELED", (
            f"subscription should stay CANCELED, got {after['lifecycle_status']}"
        )
        assert after["plan_id"] == basic["id"], f"plan_id should be unchanged, got {after['plan_id']}"


class TestPriorityReferenceBeatsCouponRedeemable:
    """Body-FK existence (ERR_REFERENCE_NOT_FOUND) outranks coupon redeemability."""

    def test_create_sub_with_bad_plan_and_exhausted_coupon_returns_reference_not_found(self, api):
        """PRD §2.7: "After path resolution, any foreign key carried in the request body — `plan_id`, `coupon_id`, or `addon_id` — must resolve to an existing resource, failing with `ERR_REFERENCE_NOT_FOUND`."
        PRD §2.7: "Next the body itself is validated for well-formedness (required fields present, enums within their allowed sets, numbers within range), failing with `ERR_INVALID_REQUEST`."
        PRD §2.7: "Only after all of the above does the system evaluate state-machine legality, returning `ERR_INVALID_STATE` when the target resource is not in a state that permits the requested transition."

        Design: Difficulty/priority_pair_validation_conflict/reference_not_found_beats_coupon_not_redeemable_on_create_sub
        """
        setup_jurisdiction_and_clock()
        basic = create_plan(tier="BASIC", monthly_fee_cents=3000, trial_days=0)
        coupon = create_coupon(
            code="EXHAUST",
            discount_type="PERCENT",
            percent_off=10,
            duration="ONCE",
            max_redemptions=1,
        )
        # Exhaust the coupon via a first account's redemption.
        acct1 = create_account(email="first@x.com")
        get_success_data(
            api.create_subscription(
                acct1["id"],
                create_subscription_payload(basic["id"], coupon_id=coupon["id"]),
                _owner(acct1["id"]),
            )
        )
        acct2 = create_account(email="second@x.com")
        res = api.create_subscription(
            acct2["id"],
            create_subscription_payload(NON_EXISTENT_PLAN_ID, coupon_id=coupon["id"]),
            _owner(acct2["id"]),
        )
        validate_error(res, "ERR_REFERENCE_NOT_FOUND")

    def test_rejected_create_creates_no_subscription(self, api):
        """PRD §2.7: "After path resolution, any foreign key carried in the request body — `plan_id`, `coupon_id`, or `addon_id` — must resolve to an existing resource, failing with `ERR_REFERENCE_NOT_FOUND`." PRD §2.7: "an existence failure always masks a later
        state or business failure".

        Design: Difficulty/priority_pair_validation_conflict/reference_not_found_beats_coupon_not_redeemable_on_create_sub
        """
        setup_jurisdiction_and_clock()
        basic = create_plan(tier="BASIC", monthly_fee_cents=3000, trial_days=0)
        coupon = create_coupon(
            code="EXHAUST",
            discount_type="PERCENT",
            percent_off=10,
            duration="ONCE",
            max_redemptions=1,
        )
        acct1 = create_account(email="first2@x.com")
        get_success_data(
            api.create_subscription(
                acct1["id"],
                create_subscription_payload(basic["id"], coupon_id=coupon["id"]),
                _owner(acct1["id"]),
            )
        )
        acct2 = create_account(email="second2@x.com")
        validate_error(
            api.create_subscription(
                acct2["id"],
                create_subscription_payload(NON_EXISTENT_PLAN_ID, coupon_id=coupon["id"]),
                _owner(acct2["id"]),
            ),
            "ERR_REFERENCE_NOT_FOUND",
        )
        from test_helpers import validate_paginated

        _, meta = validate_paginated(api.list_subscriptions(acct2["id"], _owner(acct2["id"])))
        assert meta["total_count"] == 0, (
            f"rejected create must persist no subscription, got total_count={meta['total_count']}"
        )


class TestAccountCloseBlockedByActiveSubscription:
    """Account ACTIVE->CLOSED depends on its child subscriptions' states."""

    def test_close_blocked_with_active_subscription(self, api):
        """PRD §3.9: "Closing is blocked while the account still has live commitments: if any subscription on the account is `TRIALING` or `ACTIVE`, the close is rejected with `ERR_ACCOUNT_HAS_ACTIVE_SUBS`".

        Design: Difficulty/cross_entity_state_dependency/account_close_blocked_by_active_subscription
        """
        basic, account, sub = setup_active_subscription(plan_tier="BASIC", email="cls@x.com")
        res = api.close_account(account["id"], _owner(account["id"]))
        validate_error(res, "ERR_ACCOUNT_HAS_ACTIVE_SUBS")

    def test_account_stays_active_when_close_blocked(self, api):
        """PRD §3.9: "Finally, an `AccountOwner` may **close** their account, moving `status` from `ACTIVE` to `CLOSED` and setting `mrr_cents` to 0. Closing is blocked while the account still has live commitments: if any subscription on the account is `TRIALING` or `ACTIVE`, the close is rejected with `ERR_ACCOUNT_HAS_ACTIVE_SUBS`".

        Design: Difficulty/cross_entity_state_dependency/account_close_blocked_by_active_subscription
        """
        basic, account, sub = setup_active_subscription(plan_tier="BASIC", email="cls2@x.com")
        validate_error(api.close_account(account["id"], _owner(account["id"])), "ERR_ACCOUNT_HAS_ACTIVE_SUBS")
        acct = validate_success(api.get_account(account["id"], _owner(account["id"])), 200)
        assert acct["status"] == "ACTIVE", f"account should remain ACTIVE, got {acct['status']}"


class TestChangePlanBlockedByArchivedTarget:
    """An ACTIVE subscription's change-plan depends on the target Plan's state."""

    def test_change_plan_to_archived_plan_rejected(self, api):
        """PRD §3.5: "The target plan must differ from the subscription's current `plan_id` — a no-op change is rejected with `ERR_NO_PLAN_CHANGE` — and it must not be archived, or the change is rejected with `ERR_PLAN_ARCHIVED`."

        Design: Difficulty/cross_entity_state_dependency/change_plan_blocked_by_archived_target_plan
        """
        basic, account, sub = setup_active_subscription(plan_tier="BASIC", email="cep@x.com")
        target = create_plan(tier="PRO", monthly_fee_cents=9000, trial_days=14)
        archive_plan(target["id"])
        sub_now = validate_success(api.get_subscription(sub["id"], _owner(account["id"])), 200)
        res = api.change_plan(
            account["id"],
            sub["id"],
            change_plan_payload(target["id"], sub_now["version"]),
            _owner(account["id"]),
        )
        validate_error(res, "ERR_PLAN_ARCHIVED")

    def test_change_plan_to_archived_leaves_plan_unchanged(self, api):
        """PRD §3.1: "An archived plan keeps serving the subscriptions already on it but refuses to accept new subscriptions or to be the target of a plan change; both attempts are rejected with `ERR_PLAN_ARCHIVED`".

        Design: Difficulty/cross_entity_state_dependency/change_plan_blocked_by_archived_target_plan
        """
        basic, account, sub = setup_active_subscription(plan_tier="BASIC", email="cep2@x.com")
        target = create_plan(tier="PRO", monthly_fee_cents=9000, trial_days=14)
        archive_plan(target["id"])
        sub_now = validate_success(api.get_subscription(sub["id"], _owner(account["id"])), 200)
        validate_error(
            api.change_plan(
                account["id"],
                sub["id"],
                change_plan_payload(target["id"], sub_now["version"]),
                _owner(account["id"]),
            ),
            "ERR_PLAN_ARCHIVED",
        )
        after = validate_success(api.get_subscription(sub["id"], _owner(account["id"])), 200)
        assert after["plan_id"] == basic["id"], (
            f"plan_id should stay on BASIC, got {after['plan_id']}"
        )
