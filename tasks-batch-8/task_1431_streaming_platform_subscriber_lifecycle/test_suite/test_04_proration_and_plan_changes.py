"""Upgrade proration (preview vs. posting), pause credits and clawback,
round-half-up precision, computed reads, and optimistic concurrency."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_billing_event,
    change_plan_payload,
    create_account,
    create_plan,
    create_subscription,
    get_subscription,
    list_billing_events,
    pause_subscription,
    resume_subscription,
    set_clock,
    setup_account_with_subscription,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]


def _events_for(subscription_id, event_type=None):
    return list_billing_events(subscription_id=subscription_id,
                               event_type=event_type)


class TestProrationPreviewVsPosting:
    """The preview reads the request-time clock; the actual posting reads the
    posting-time clock — one day apart the two figures diverge by exactly the
    per-day rate differential."""

    def test_preview_at_request_instant(self):
        """PRD section 3.5: "The proration-preview capability takes a
        `target_plan_id` and returns the `net_charge_cents`,
        `unused_credit_cents`, and `prorated_charge_cents` that the same
        formula produces, evaluated at the request's own instant — the preview
        is an optimistic estimate only and is never persisted to the ledger."

        Design: Difficulty/dual_variant_calc/proration_upgrade_optimistic_vs_final
        """
        plan_basic, account, sub = setup_account_with_subscription(
            plan_overrides={"plan_code": "BASIC", "tier": "BASIC",
                            "monthly_price_cents": 3000}
        )
        plan_premium = create_plan(plan_code="PREMIUM", tier="PREMIUM",
                                   monthly_price_cents=6000, max_profiles=5,
                                   max_households=2)
        # Period runs 2026-08-01..2026-08-31 (30 days nominal); at 2026-08-11
        # there are 20 whole days remaining.
        set_clock("2026-08-11T00:00:00Z")
        resp = api_client.proration_preview(
            sub["subscription_id"], ADMIN,
            params={"target_plan_id": plan_premium["plan_id"]},
        )
        data = validate_success(resp, expected_status=200)
        # unused credit = round_half_up(3000 * 20/30) = 2000
        # prorated charge = round_half_up(6000 * 20/30) = 4000
        # net = 4000 - 2000 = 2000
        assert data["unused_credit_cents"] == 2000
        assert data["prorated_charge_cents"] == 4000
        assert data["net_charge_cents"] == 2000, (
            f"preview at 20/30 days remaining must net 2000, got "
            f"{data['net_charge_cents']}"
        )

    def test_posting_one_day_later_differs_by_per_day_rate(self):
        """PRD section 3.5: "the unused credit is the current price
        (grandfathered when locked, else list) times days remaining over days
        in period, rounded half up to whole cents; the prorated charge is the
        target plan's `monthly_price_cents` over the same day fraction,
        likewise rounded half up; and the net charge is the prorated charge
        minus the unused credit — each component rounded before the
        subtraction, never after."

        Design: Difficulty/dual_variant_calc/proration_upgrade_optimistic_vs_final
        """
        plan_basic, account, sub = setup_account_with_subscription(
            plan_overrides={"plan_code": "BASIC", "tier": "BASIC",
                            "monthly_price_cents": 3000}
        )
        plan_premium = create_plan(plan_code="PREMIUM", tier="PREMIUM",
                                   monthly_price_cents=6000, max_profiles=5,
                                   max_households=2)
        set_clock("2026-08-11T00:00:00Z")
        resp = api_client.proration_preview(
            sub["subscription_id"], ADMIN,
            params={"target_plan_id": plan_premium["plan_id"]},
        )
        preview = validate_success(resp, expected_status=200)
        assert preview["net_charge_cents"] == 2000

        set_clock("2026-08-12T00:00:00Z")
        sub_now = get_subscription(sub["subscription_id"])
        resp = api_client.change_plan(
            sub["subscription_id"],
            change_plan_payload(plan_premium["plan_id"], sub_now["version"]),
            ADMIN,
        )
        validate_success(resp, expected_status=200)
        # At 2026-08-12 there are 19 days remaining: credit = 1900,
        # charge = 3800, net = 1900 — exactly the per-day differential (100)
        # below the preview's 2000. PRD §3.5: "The posting lands on the ledger
        # as a `CHARGE` and `PRORATION_CREDIT` pair", so the net effect is
        # CHARGE + PRORATION_CREDIT.
        all_events = _events_for(sub["subscription_id"])
        charge_events = [e for e in all_events if e["event_type"] == "CHARGE"]
        credit_events = [e for e in all_events if e["event_type"] == "PRORATION_CREDIT"]
        assert charge_events, "an upgrade posts a CHARGE event"
        assert credit_events, "an upgrade posts a PRORATION_CREDIT event"
        posted_net = charge_events[-1]["amount_cents"] + credit_events[-1]["amount_cents"]
        assert posted_net == 1900, (
            f"posting one day later must net 1900 (19/30 days), got "
            f"{posted_net}; the preview figure 2000 was evaluated at the "
            f"earlier request instant"
        )
        assert posted_net != preview["net_charge_cents"]


class TestPauseCreditAndClawback:

    def test_pause_posts_provisional_proration_credit(self):
        """PRD section 3.5: "That provisional credit posts immediately as a
        single negative `PRORATION_CREDIT` event."

        Design: Difficulty/dual_variant_calc/pause_credit_provisional_vs_final_clawback
        """
        _plan, account, sub = setup_account_with_subscription(
            plan_overrides={"monthly_price_cents": 3000}
        )
        # 2026-08-11: 20 whole days remain of the 30-day period.
        set_clock("2026-08-11T00:00:00Z")
        pause_subscription(sub["subscription_id"], duration_months=1)
        credits = _events_for(sub["subscription_id"],
                              event_type="PRORATION_CREDIT")
        assert credits, "pause must post a PRORATION_CREDIT event"
        # credit = round_half_up(3000 * 20/30) = 2000, posted negative.
        assert credits[-1]["amount_cents"] == -2000, (
            f"provisional credit must be -2000 (3000 * 20/30), got "
            f"{credits[-1]['amount_cents']}"
        )

    def test_resume_posts_correcting_clawback_event(self):
        """PRD section 3.5: "When a subscription resumes before
        `period_end_utc`, the credit is recomputed using the actual paused
        duration, and the delta between the provisional credit and the final
        figure posts as a correcting billing event."

        Design: Difficulty/dual_variant_calc/pause_credit_provisional_vs_final_clawback
        """
        _plan, account, sub = setup_account_with_subscription(
            plan_overrides={"monthly_price_cents": 3000}
        )
        set_clock("2026-08-11T00:00:00Z")
        pause_subscription(sub["subscription_id"], duration_months=1)
        provisional = _events_for(sub["subscription_id"],
                                  event_type="PRORATION_CREDIT")[-1]
        # Resume 10 days into the pause, before period end.
        set_clock("2026-08-21T00:00:00Z")
        resume_subscription(sub["subscription_id"])
        all_events = _events_for(sub["subscription_id"])
        after_resume = [
            e for e in all_events
            if e["billing_event_id"] != provisional["billing_event_id"]
        ]
        assert after_resume, "resume must post further ledger activity"
        # The resume-side posting reflects the actual 10-day paused duration,
        # not the provisional 20-day figure, so its amount differs.
        assert any(
            e["amount_cents"] != provisional["amount_cents"] for e in after_resume
        ), (
            "the correcting event must differ from the provisional credit "
            "because the final clawback uses the actual paused duration"
        )
        for event in all_events:
            assert_billing_event(event)


class TestProrationRounding:

    def test_preview_rounds_half_up_per_component(self):
        """PRD section 2.6: "Where a computation produces more than one
        monetary component (as in the upgrade proration of §3.5), each
        component is individually rounded half up to whole cents first, and
        only then are the rounded components combined — the net figure is a
        subtraction of already-rounded values, never a rounding of a raw
        difference."

        Design: Corner/calculations/proration_preview_rounding_half_up
        """
        plan_basic, account, sub = setup_account_with_subscription(
            plan_overrides={"plan_code": "BASIC", "tier": "BASIC",
                            "monthly_price_cents": 3000}
        )
        plan_premium = create_plan(plan_code="PREMIUM", tier="PREMIUM",
                                   monthly_price_cents=6000, max_profiles=5,
                                   max_households=2)
        # 2026-08-24: 7 whole days remain of the 30-day period.
        set_clock("2026-08-24T00:00:00Z")
        resp = api_client.proration_preview(
            sub["subscription_id"], ADMIN,
            params={"target_plan_id": plan_premium["plan_id"]},
        )
        data = validate_success(resp, expected_status=200)
        # round_half_up(3000 * 7/30) = round_half_up(700.0) = 700
        # round_half_up(6000 * 7/30) = round_half_up(1400.0) = 1400
        assert data["unused_credit_cents"] == 700
        assert data["prorated_charge_cents"] == 1400
        assert data["net_charge_cents"] == 700


class TestProrationPreviewComputedRead:

    def test_preview_returns_components_without_persisting(self):
        """PRD section 3.5: "Subscribers can preview the cost of a hypothetical
        change before committing. The proration-preview capability takes a
        `target_plan_id` and returns the `net_charge_cents`,
        `unused_credit_cents`, and `prorated_charge_cents` that the same
        formula produces, evaluated at the request's own instant — the preview
        is an optimistic estimate only and is never persisted to the ledger."

        Design: Corner/endpoints/proration_preview_computed_read
        """
        plan_basic, account, sub = setup_account_with_subscription(
            plan_overrides={"plan_code": "BASIC", "tier": "BASIC",
                            "monthly_price_cents": 3000}
        )
        plan_premium = create_plan(plan_code="PREMIUM", tier="PREMIUM",
                                   monthly_price_cents=6000, max_profiles=5,
                                   max_households=2)
        resp = api_client.proration_preview(
            sub["subscription_id"], ADMIN,
            params={"target_plan_id": plan_premium["plan_id"]},
        )
        data = validate_success(resp, expected_status=200)
        for field in ("net_charge_cents", "unused_credit_cents",
                      "prorated_charge_cents"):
            assert isinstance(data.get(field), int), (
                f"preview must return integer {field}, got {data.get(field)!r}"
            )
        after = get_subscription(sub["subscription_id"])
        assert after["plan_id"] == plan_basic["plan_id"], (
            "the preview is never persisted: the subscription must still be "
            "on its original plan"
        )
        assert after["pending_plan_id"] in (None, plan_basic["plan_id"]) or \
            after["pending_plan_id"] is None


class TestChangePlanOcc:

    def test_stale_expected_version_rejected(self):
        """PRD section 2.9: "A plan change on a subscription must carry
        `expected_subscription_version`, holding the caller's last observed
        `version` of the target subscription; if the subscription's current
        `version` has advanced since that observation — because a price-change
        sweep, a scheduled downgrade, or a save-offer acceptance mutated it in
        the interim — the request is rejected with `ERR_STALE_VERSION` (HTTP
        412), and nothing is written."

        Design: Corner/errors/stale_version_on_change_plan_returns_412
        """
        plan_basic, account, sub = setup_account_with_subscription(
            plan_overrides={"plan_code": "BASIC", "tier": "BASIC",
                            "monthly_price_cents": 3000}
        )
        plan_standard = create_plan(plan_code="STANDARD", tier="STANDARD",
                                    monthly_price_cents=4500, max_profiles=3,
                                    max_households=2)
        plan_premium = create_plan(plan_code="PREMIUM", tier="PREMIUM",
                                   monthly_price_cents=6000, max_profiles=5,
                                   max_households=2)
        stale_version = sub["version"]
        # An intervening mutation (a successful upgrade) advances the
        # subscription's version without changing its state, so the stale
        # expected_version is the only failing check on the second call.
        resp = api_client.change_plan(
            sub["subscription_id"],
            change_plan_payload(plan_standard["plan_id"], stale_version),
            ADMIN,
        )
        validate_success(resp, expected_status=200)
        resp = api_client.change_plan(
            sub["subscription_id"],
            change_plan_payload(plan_premium["plan_id"], stale_version),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_version_increments_on_every_mutation(self):
        """PRD section 2.5: "`version` (integer): A system-managed integer
        that increments by one with every modification to the resource, and
        serves as the basis for optimistic concurrency control (§2.9)."

        Design: Corner/cross_cutting_complexity_layers/occ_subscription_version_increments_on_every_write
        """
        _plan, _account, sub = setup_account_with_subscription()
        v1 = sub["version"]
        pause_subscription(sub["subscription_id"], duration_months=1)
        after = get_subscription(sub["subscription_id"])
        assert after["version"] == v1 + 1, (
            f"a successful mutation must increment version by exactly one: "
            f"was {v1}, now {after['version']}"
        )


class TestValidationPriorityOnChangePlan:

    def test_invalid_state_beats_plan_rule_violation(self):
        """PRD section 2.8: "Every request passes through a fixed validation
        pipeline, and the ordering is part of the contract: when several
        checks would fail, the failure reported is the one belonging to the
        earliest stage."
        PRD section 2.8: "4. **State** — the target resource must be in a
        state from which the requested transition is allowed; this guards
        every state-transition endpoint (cancel, pause, resume, recover,
        accept, decline, reconcile, and the like) and surfaces
        `ERR_INVALID_STATE` (409)."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_plan_rule_on_change_plan
        """
        from test_helpers import (
            cancel_subscription,
            create_plan_payload,
            setup_account_with_subscription,
        )
        plan_basic, account, sub = setup_account_with_subscription(
            plan_overrides={"plan_code": "BASIC", "tier": "BASIC",
                            "monthly_price_cents": 3000}
        )
        plan_old = create_plan(plan_code="OLD", tier="BASIC",
                               monthly_price_cents=2000, max_profiles=1,
                               max_households=1)
        resp = api_client.archive_plan(plan_old["plan_id"], ADMIN)
        validate_success(resp, expected_status=200)
        cancel_subscription(sub["subscription_id"])
        # Two failures coincide: the subscription is CANCELLED (stage 4,
        # state) and the target plan is archived (stage 8, plan rules).
        resp = api_client.change_plan(
            sub["subscription_id"],
            change_plan_payload(plan_old["plan_id"], sub["version"]),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_invalid_state_on_change_plan_of_cancelled_even_with_valid_target(self):
        """PRD section 2.8: "4. **State** — the target resource must be in a
        state from which the requested transition is allowed; this guards
        every state-transition endpoint (cancel, pause, resume, recover,
        accept, decline, reconcile, and the like) and surfaces
        `ERR_INVALID_STATE` (409)."
        PRD section 3.6: "All of `CANCELLED` and `EXPIRED` are terminal."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_plan_rule_on_change_plan
        """
        from test_helpers import cancel_subscription
        plan_basic, account, sub = setup_account_with_subscription(
            plan_overrides={"plan_code": "BASIC", "tier": "BASIC",
                            "monthly_price_cents": 3000}
        )
        plan_premium = create_plan(plan_code="PREMIUM", tier="PREMIUM",
                                   monthly_price_cents=6000, max_profiles=5,
                                   max_households=2)
        cancel_subscription(sub["subscription_id"])
        # Isolated state failure: the target plan is a perfectly valid
        # upgrade, so only the terminal-state guard can fire.
        resp = api_client.change_plan(
            sub["subscription_id"],
            change_plan_payload(plan_premium["plan_id"], sub["version"]),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
