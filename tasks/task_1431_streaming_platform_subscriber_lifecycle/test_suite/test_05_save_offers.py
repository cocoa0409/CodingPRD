"""Save offers: discount pricing branches, accept/decline semantics, expiry,
supersession on cancel, and cross-entity dependence on price changes."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_save_offer,
    cancel_subscription,
    create_price_change_notice,
    create_save_offer,
    get_save_offer,
    get_subscription,
    make_subscriber_headers,
    run_sweeps,
    set_clock,
    setup_account_with_subscription,
    setup_subscription_with_presented_offer,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]


class TestDiscountOfferPricing:
    """Mode (a) combinatorial: the discounted lock depends on the plan list
    price, whether a grandfathered lock exists, and the discount percent, with
    piecewise branches at 0 and 100 (PRD section 3.6)."""

    def test_discount_accept_locks_half_of_list_price(self):
        """PRD section 3.6: "Accepting `DISCOUNT_50_3M` locks a discounted
        `grandfathered_price_cents` for `discount_duration_months`: the base
        is the subscription's existing `grandfathered_price_cents` when one
        is locked, otherwise the plan's list price; a `discount_pct` of 100
        or more makes the price free, a `discount_pct` of zero or less keeps
        the base, and anything in between locks the base multiplied by the
        complement of the discount over one hundred, rounded half up to whole
        cents."

        Design: Difficulty/combinatorial_formula/save_offer_discount_nonlinear_branches
        """
        plan, account, sub, offer = setup_subscription_with_presented_offer(
            offer_type="DISCOUNT_50_3M",
            plan_overrides={"plan_code": "PREMIUM", "tier": "PREMIUM",
                            "monthly_price_cents": 6000, "max_profiles": 5,
                            "max_households": 2},
            offer_overrides={"discount_pct": 50, "discount_duration_months": 3},
        )
        resp = api_client.accept_save_offer(
            offer["save_offer_id"], make_subscriber_headers(account["account_id"])
        )
        validate_success(resp, expected_status=200)
        current = get_subscription(sub["subscription_id"])
        # No prior lock: base = plan list 6000; 50% off -> 3000.
        assert current["grandfathered_price_cents"] == 3000, (
            f"50% discount off the 6000 list price must lock 3000, got "
            f"{current['grandfathered_price_cents']}"
        )

    def test_full_discount_locks_zero(self):
        """PRD section 3.6: "a `discount_pct` of 100 or more makes the price
        free, a `discount_pct` of zero or less keeps the base, and anything in
        between locks the base multiplied by the complement of the discount
        over one hundred, rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/save_offer_discount_nonlinear_branches
        """
        plan, account, sub, offer = setup_subscription_with_presented_offer(
            offer_type="DISCOUNT_50_3M",
            plan_overrides={"monthly_price_cents": 3000},
            offer_overrides={"discount_pct": 100, "discount_duration_months": 3},
        )
        resp = api_client.accept_save_offer(
            offer["save_offer_id"], make_subscriber_headers(account["account_id"])
        )
        validate_success(resp, expected_status=200)
        current = get_subscription(sub["subscription_id"])
        assert current["grandfathered_price_cents"] == 0, (
            f"a discount_pct of 100 makes the price free, got "
            f"{current['grandfathered_price_cents']}"
        )


class TestOfferAnsweredOnce:

    def test_second_accept_returns_invalid_state(self):
        """PRD section 3.6: "acceptance moves it `PRESENTED → ACCEPTED` and is
        guarded twice: the offer must not have reached `expires_at_utc` (an
        expired acceptance is rejected with `ERR_OFFER_EXPIRED`, and the sweep
        moves unanswered offers to `EXPIRED` at that instant), and the
        subscription must stand in `ACTIVE` or `TRIALING` (anything else is
        `ERR_INVALID_STATE`)."
        PRD section 2.8: "4. **State** — the target resource must be in a
        state from which the requested transition is allowed; this guards
        every state-transition endpoint (cancel, pause, resume, recover,
        accept, decline, reconcile, and the like) and surfaces
        `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/idempotent_second_accept_fails
        """
        _plan, account, sub, offer = setup_subscription_with_presented_offer(
            offer_type="PAUSE_1M"
        )
        subscriber = make_subscriber_headers(account["account_id"])
        first = api_client.accept_save_offer(offer["save_offer_id"], subscriber)
        validate_success(first, expected_status=200)
        resp = api_client.accept_save_offer(offer["save_offer_id"], subscriber)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestCancelSupersedesOffer:

    def test_cancel_flips_presented_offer_to_superseded(self):
        """PRD section 3.6: "cancelling from `ACTIVE` additionally flips any
        save offer still `PRESENTED` on the subscription to `SUPERSEDED` and
        clears any scheduled `pending_plan_id`."

        Design: Difficulty/transitive_cascade/cancel_supersedes_presented_save_offer
        """
        _plan, _account, sub, offer = setup_subscription_with_presented_offer(
            offer_type="PAUSE_1M"
        )
        cancel_subscription(sub["subscription_id"])
        current_offer = get_save_offer(offer["save_offer_id"])
        assert current_offer["offer_status"] == "SUPERSEDED", (
            f"cancel must supersede the still-PRESENTED offer, got "
            f"{current_offer['offer_status']}"
        )
        current_sub = get_subscription(sub["subscription_id"])
        assert current_sub["subscription_status"] == "CANCELLED"

    def test_superseded_offer_is_terminal_for_accept(self):
        """PRD section 3.6: "cancelling from `ACTIVE` additionally flips any
        save offer still `PRESENTED` on the subscription to `SUPERSEDED`".
        PRD section 2.8: "4. **State** — the target resource must be in a
        state from which the requested transition is allowed; this guards
        every state-transition endpoint (cancel, pause, resume, recover,
        accept, decline, reconcile, and the like) and surfaces
        `ERR_INVALID_STATE` (409)."

        Design: Difficulty/transitive_cascade/cancel_supersedes_presented_save_offer
        """
        _plan, account, sub, offer = setup_subscription_with_presented_offer(
            offer_type="PAUSE_1M"
        )
        cancel_subscription(sub["subscription_id"])
        # SUPERSEDED is terminal: a late accept is a state-guard failure.
        resp = api_client.accept_save_offer(
            offer["save_offer_id"], make_subscriber_headers(account["account_id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestOfferExpiryPrecedence:

    def test_expired_acceptance_surfaces_offer_expired(self):
        """PRD section 3.6: "acceptance moves it `PRESENTED → ACCEPTED` and is
        guarded twice: the offer must not have reached `expires_at_utc` (an
        expired acceptance is rejected with `ERR_OFFER_EXPIRED`, and the sweep
        moves unanswered offers to `EXPIRED` at that instant)".
        PRD section 2.8: "Every request passes through a fixed validation
        pipeline, and the ordering is part of the contract: when several
        checks would fail, the failure reported is the one belonging to the
        earliest stage."

        Design: Difficulty/priority_pair_validation_conflict/temporal_offer_expiry_beats_referential_consistency
        """
        plan, account, sub = setup_account_with_subscription(
            plan_overrides={"plan_code": "BASIC", "tier": "BASIC",
                            "monthly_price_cents": 3000}
        )
        from test_helpers import create_plan
        plan_old = create_plan(plan_code="OLD2", tier="BASIC",
                               monthly_price_cents=2000, max_profiles=1,
                               max_households=1)
        offer = create_save_offer(
            sub["subscription_id"], offer_type="DOWNGRADE",
            target_plan_id=plan_old["plan_id"],
        )
        # Archiving the target after the offer exists leaves the offer's body
        # reference pointing at an archived plan, so both the temporal check
        # (offer expired — stage 6) and the referential-consistency check
        # (stage 7) would fail; the earlier stage wins. We do NOT run the
        # expiry sweep — the offer remains PRESENTED but past its
        # expires_at_utc, isolating the temporal guard from the state guard.
        resp = api_client.archive_plan(plan_old["plan_id"], ADMIN)
        validate_success(resp, expected_status=200)
        # 2026-08-05 is past the offer's 72-hour expiry (2026-08-04), but no
        # sweep has run, so offer_status is still PRESENTED.
        set_clock("2026-08-05T00:00:00Z")
        resp = api_client.accept_save_offer(
            offer["save_offer_id"], make_subscriber_headers(account["account_id"])
        )
        validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED)

    def test_expired_offer_moved_to_expired_by_sweep(self):
        """PRD section 3.6: "The offer is born `PRESENTED`, stamped with
        `presented_at_utc`, and given exactly 72 hours of life — its
        `expires_at_utc` is 72 hours after presentation."
        PRD section 3.6: "the sweep moves unanswered offers to `EXPIRED` at
        that instant".

        Design: Difficulty/priority_pair_validation_conflict/temporal_offer_expiry_beats_referential_consistency
        """
        _plan, _account, _sub, offer = setup_subscription_with_presented_offer(
            offer_type="PAUSE_1M"
        )
        # 72 hours after the 2026-08-01 presentation is 2026-08-04T00:00:00Z.
        run_sweeps("2026-08-06T00:00:00Z")
        current = get_save_offer(offer["save_offer_id"])
        assert current["offer_status"] == "EXPIRED", (
            f"an unanswered offer must be moved to EXPIRED by the sweep at "
            f"its expiry instant, got {current['offer_status']}"
        )


class TestOfferAcceptWithPriceChangeNotice:

    def test_accept_discount_uses_current_list_price_before_notice_effective(self):
        """PRD section 3.6: "Accepting `DISCOUNT_50_3M` locks a discounted
        `grandfathered_price_cents` for `discount_duration_months`: the base
        is the subscription's existing `grandfathered_price_cents` when one
        is locked, otherwise the plan's list price".
        PRD section 3.7: "When the logical clock reaches `effective_at_utc`,
        the sweep moves the notice `ANNOUNCED → EFFECTIVE`".

        Design: Difficulty/cross_entity_state_dependency/save_offer_accept_depends_on_price_change_notice
        """
        plan, account, sub = setup_account_with_subscription(
            plan_overrides={"plan_code": "BASIC", "tier": "BASIC",
                            "monthly_price_cents": 3000}
        )
        # Announce a 3000 -> 4000 change effective 2026-09-01 (still ANNOUNCED
        # at accept time, so the plan list price is still 3000).
        create_price_change_notice(
            plan["plan_id"], old_price_cents=3000, new_price_cents=4000,
            effective_at_utc="2026-09-01T00:00:00Z",
            grandfather_period_months=6,
        )
        offer = create_save_offer(
            sub["subscription_id"], offer_type="DISCOUNT_50_3M",
            discount_pct=50, discount_duration_months=3,
        )
        # Accept within the offer's 72-hour validity window (presented at
        # 2026-08-01, expires 2026-08-04) and still well before the notice's
        # 2026-09-01 effective instant.
        set_clock("2026-08-02T00:00:00Z")
        resp = api_client.accept_save_offer(
            offer["save_offer_id"], make_subscriber_headers(account["account_id"])
        )
        data = validate_success(resp, expected_status=200)
        assert data["offer_status"] == "ACCEPTED"
        current = get_subscription(sub["subscription_id"])
        # No prior lock, and the notice is not yet effective: base = list
        # 3000; 50% off -> 1500.
        assert current["grandfathered_price_cents"] == 1500, (
            f"acceptance before the notice's effective instant bases the "
            f"discount on the current 3000 list price, got "
            f"{current['grandfathered_price_cents']}"
        )

    def test_offer_accept_still_valid_while_notice_pending(self):
        """PRD section 3.6: "acceptance moves it `PRESENTED → ACCEPTED` and is
        guarded twice: the offer must not have reached `expires_at_utc` (an
        expired acceptance is rejected with `ERR_OFFER_EXPIRED`, and the sweep
        moves unanswered offers to `EXPIRED` at that instant), and the
        subscription must stand in `ACTIVE` or `TRIALING` (anything else is
        `ERR_INVALID_STATE`)."

        Design: Difficulty/cross_entity_state_dependency/save_offer_accept_depends_on_price_change_notice
        """
        plan, account, sub = setup_account_with_subscription(
            plan_overrides={"plan_code": "BASIC", "tier": "BASIC",
                            "monthly_price_cents": 3000}
        )
        notice = create_price_change_notice(
            plan["plan_id"], old_price_cents=3000, new_price_cents=4000,
            effective_at_utc="2026-09-01T00:00:00Z",
            grandfather_period_months=6,
        )
        assert notice["notice_status"] == "ANNOUNCED"
        offer = create_save_offer(
            sub["subscription_id"], offer_type="DISCOUNT_50_3M",
            discount_pct=50, discount_duration_months=3,
        )
        resp = api_client.accept_save_offer(
            offer["save_offer_id"], make_subscriber_headers(account["account_id"])
        )
        data = validate_success(resp, expected_status=200)
        assert_save_offer(data)
        assert data["offer_status"] == "ACCEPTED", (
            "a pending (ANNOUNCED) price change notice does not block "
            "save-offer acceptance"
        )


class TestDeclineLeavesSubscriptionUnchanged:

    def test_decline_moves_offer_and_leaves_subscription(self):
        """PRD section 3.6: "Declining moves it `PRESENTED → DECLINED` with no
        further effect".

        Design: Difficulty/compensating_invariant/save_offer_accept_then_decline_leaves_subscription_unchanged
        """
        plan, account, sub, offer = setup_subscription_with_presented_offer(
            offer_type="DISCOUNT_50_3M",
            plan_overrides={"monthly_price_cents": 3000},
            offer_overrides={"discount_pct": 50, "discount_duration_months": 3},
        )
        resp = api_client.decline_save_offer(
            offer["save_offer_id"], make_subscriber_headers(account["account_id"])
        )
        data = validate_success(resp, expected_status=200)
        assert data["offer_status"] == "DECLINED"
        current = get_subscription(sub["subscription_id"])
        assert current["grandfathered_price_cents"] is None, (
            "a declined discount offer must not touch the subscription's "
            "grandfathered_price_cents"
        )
        assert current["subscription_status"] == "ACTIVE"

    def test_decline_preserves_effective_price(self):
        """PRD section 3.6: "Declining moves it `PRESENTED → DECLINED` with no
        further effect".
        PRD section 3.5: "The credit equals the subscription's current price —
        its `grandfathered_price_cents` when one is locked in, otherwise the
        plan's list `monthly_price_cents`".

        Design: Difficulty/compensating_invariant/save_offer_accept_then_decline_leaves_subscription_unchanged
        """
        plan, account, sub, offer = setup_subscription_with_presented_offer(
            offer_type="DISCOUNT_50_3M",
            plan_overrides={"monthly_price_cents": 3000},
            offer_overrides={"discount_pct": 50, "discount_duration_months": 3},
        )
        before = get_subscription(sub["subscription_id"])
        api_client.decline_save_offer(
            offer["save_offer_id"], make_subscriber_headers(account["account_id"])
        )
        after = get_subscription(sub["subscription_id"])
        # Effective price = COALESCE(grandfathered_price_cents, list price):
        # before and after decline it is the plan's 3000 list price.
        effective_before = before["grandfathered_price_cents"] \
            if before["grandfathered_price_cents"] is not None \
            else plan["monthly_price_cents"]
        effective_after = after["grandfathered_price_cents"] \
            if after["grandfathered_price_cents"] is not None \
            else plan["monthly_price_cents"]
        assert effective_before == 3000
        assert effective_after == effective_before, (
            f"declining must leave the effective price unchanged: was "
            f"{effective_before}, now {effective_after}"
        )
