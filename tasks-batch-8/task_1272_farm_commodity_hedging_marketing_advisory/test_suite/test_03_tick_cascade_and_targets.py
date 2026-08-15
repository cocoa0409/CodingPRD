"""Market-tick cascade: target triggers, headroom-sized recommendation minting,
TTL expiry, and the SUSPENDED-plan gate."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_grower_headers,
    setup_operation_with_active_plan,
    create_accepted_recommendation,
    record_settlement_tick,
    record_quote_tick,
    set_logical_clock,
    create_price_target_payload,
)

ADVISOR = TEST_USERS["advisor_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestTickCascade:
    def test_tick_fires_eligible_targets_in_pinned_order(self, api):
        """PRD §3.4: "Eligible targets fire in `target_price` ascending order
        with ties broken by `created_at` ascending. Each fired target moves
        from `PENDING` to `TRIGGERED` and mints a `PROPOSED` hedge
        recommendation whose `price_target_id` points back to the originating
        target, recording the minted recommendation's id in the target's
        `recommendation_id`."

        Design: Difficulty/transitive_cascade/market_tick_cascade_target_recommendation_plan
        """
        ctx = setup_operation_with_active_plan(
            name="Cascade Farm", risk_profile="BALANCED", planted_acres=1000, max_priced_pct=0.10
        )
        plan_id = ctx["plan"]["id"]
        t1 = get_success_data(api.create_price_target(
            {"plan_id": plan_id, "contract_month": "2026-12", "target_price": 4.50, "increment_bushels": 10000}, ADVISOR))
        t3 = get_success_data(api.create_price_target(
            {"plan_id": plan_id, "contract_month": "2026-12", "target_price": 4.50, "increment_bushels": 10000}, ADVISOR))
        get_success_data(api.create_price_target(
            {"plan_id": plan_id, "contract_month": "2026-12", "target_price": 4.60, "increment_bushels": 10000}, ADVISOR))
        record_settlement_tick(4.60, "2026-07-01")
        t1_after = get_success_data(api.get_price_target(t1["id"], ADVISOR))
        t3_after = get_success_data(api.get_price_target(t3["id"], ADVISOR))
        assert t1_after["status"] == "TRIGGERED" and t1_after["recommendation_id"], (
            "earliest-created 4.50 target must fire first and record its minted recommendation"
        )
        assert t3_after["status"] == "TRIGGERED" and t3_after["recommendation_id"], (
            "same-price later-created target fires second while headroom remains"
        )
        assert t1_after["recommendation_id"] != t3_after["recommendation_id"]

    def test_headroom_exhaustion_lapses_later_target(self, api):
        """PRD §3.4: "The minted recommendation's size is the smaller of the
        target's `increment_bushels` and the pending headroom, floored at zero.
        Pending headroom is the plan's `coverage_cap_bushels` minus
        `hedged_bushels` minus `priced_contract_bushels` minus the sum of
        bushels over the plan's currently `PROPOSED` recommendations — pending
        advice reserves capacity during one tick sweep so that a single tick
        cannot mint recommendations past the cap. When the pending headroom is
        zero or negative, the target goes `LAPSED` instead of `TRIGGERED` and
        no recommendation is minted."
        PRD §3.3: "`pending_recommendation_count` counts the plan's hedge
        recommendations in `PROPOSED` status."

        Design: Difficulty/transitive_cascade/market_tick_cascade_target_recommendation_plan
        """
        ctx = setup_operation_with_active_plan(
            name="Cascade Farm", risk_profile="BALANCED", planted_acres=1000, max_priced_pct=0.10
        )
        plan_id = ctx["plan"]["id"]
        # cap = floor(200000 * min(0.10, 0.80)) = 20000 headroom.
        get_success_data(api.create_price_target(
            {"plan_id": plan_id, "contract_month": "2026-12", "target_price": 4.50, "increment_bushels": 10000}, ADVISOR))
        get_success_data(api.create_price_target(
            {"plan_id": plan_id, "contract_month": "2026-12", "target_price": 4.50, "increment_bushels": 10000}, ADVISOR))
        t2 = get_success_data(api.create_price_target(
            {"plan_id": plan_id, "contract_month": "2026-12", "target_price": 4.60, "increment_bushels": 10000}, ADVISOR))
        record_settlement_tick(4.60, "2026-07-01")
        t2_after = get_success_data(api.get_price_target(t2["id"], ADVISOR))
        assert t2_after["status"] == "LAPSED", (
            "headroom exhausted (20000 cap - 20000 minted): the last target must LAPSE"
        )
        recs, _meta = validate_paginated(api.list_recommendations(
            ADVISOR, params={"plan_id": plan_id, "status": "PROPOSED"}))
        assert len(recs) == 2, f"exactly 2 PROPOSED recommendations must be minted, got {len(recs)}"
        assert all(r["bushels"] == 10000 for r in recs)
        plan = get_success_data(api.get_plan(plan_id, ADVISOR))
        assert plan["pending_recommendation_count"] == 2, (
            "hop 3 lands on the plan: pending_recommendation_count must equal 2"
        )


class TestSuspendedPlanGate:
    def test_suspended_plan_skips_target_triggers(self, api):
        """PRD §3.3: "While a plan is `SUSPENDED`, price-target triggers are
        skipped for that plan, and both sales-contract creation and
        recommendation acceptance against the plan are rejected with
        `ERR_INVALID_STATE`."
        PRD §3.4: "A target is eligible when the tick's commodity equals the
        operation's `primary_commodity` for the target's plan, the tick's
        `contract_month` equals the target's `contract_month`, the tick's
        `price` is greater than or equal to the target's `target_price`, and
        the target's plan is `ACTIVE`. Both `QUOTE` and `SETTLEMENT` ticks fire
        targets."

        Design: Corner/cross_cutting_complexity_layers/suspended_plan_skips_target_triggers
        """
        ctx = setup_operation_with_active_plan(
            name="Gate Farm", risk_profile="BALANCED", max_priced_pct=0.80
        )
        plan_id = ctx["plan"]["id"]
        target = get_success_data(api.create_price_target(
            {"plan_id": plan_id, "contract_month": "2026-12", "target_price": 4.80, "increment_bushels": 5000}, ADVISOR))
        get_success_data(api.suspend_plan(plan_id, ADVISOR))
        record_quote_tick(4.90, "2026-05-02")
        during = get_success_data(api.get_price_target(target["id"], ADVISOR))
        assert during["status"] == "PENDING", "a qualifying tick must not fire targets while the plan is SUSPENDED"
        get_success_data(api.resume_plan(plan_id, ADVISOR))
        record_quote_tick(4.91, "2026-05-03")
        after = get_success_data(api.get_price_target(target["id"], ADVISOR))
        assert after["status"] == "TRIGGERED", "after resume the next qualifying tick must fire the target"
        assert after["recommendation_id"], "the fired target must record its minted recommendation"
        rec = get_success_data(api.get_recommendation(after["recommendation_id"], ADVISOR))
        assert rec["status"] == "PROPOSED"


class TestRecommendationLifecycle:
    def test_accepted_recommendation_cannot_be_rejected(self, api):
        """PRD §3.5: "Rejection moves a `PROPOSED` recommendation to
        `REJECTED`, decrements `pending_recommendation_count` by one, and —
        when `price_target_id` is set — moves the originating target to
        `LAPSED`."
        PRD §2.6: "Sixth, the target resource must be in a from-state that
        permits the requested transition, producing `ERR_INVALID_STATE`."

        Design: Corner/state_machines/accepted_recommendation_cannot_be_rejected
        """
        ctx = setup_operation_with_active_plan(
            name="InvT Farm", risk_profile="BALANCED", planted_acres=1000, max_priced_pct=0.80
        )
        rec = create_accepted_recommendation(ctx["plan"], ctx["operation"]["id"], bushels=1000)
        assert rec["status"] == "ACCEPTED"
        resp = api.reject_recommendation(rec["id"], make_grower_headers(ctx["operation"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_recommendation(rec["id"], ADVISOR))
        assert after["status"] == "ACCEPTED", "recommendation must remain ACCEPTED after the rejected reject"

    def test_recommendation_ttl_expiry_via_tick_sweep(self, api):
        """PRD §3.4: "On the second hop, recommendation expiry runs: any
        `PROPOSED` recommendation whose `created_at` is more than five days
        before the current logical clock moves to `EXPIRED`. Expiry decrements
        the plan's `pending_recommendation_count` by one and, when the
        recommendation's `price_target_id` is set, moves the originating target
        to `LAPSED`."
        PRD §1: "At startup and before any administrative action, the logical
        clock reads exactly `2026-05-01T00:00:00Z`."

        Design: Corner/calculations/recommendation_ttl_expiry_via_tick_sweep
        """
        ctx = setup_operation_with_active_plan(
            name="TTL Farm", risk_profile="BALANCED", max_priced_pct=0.80
        )
        plan_id = ctx["plan"]["id"]
        target = get_success_data(api.create_price_target(
            {"plan_id": plan_id, "contract_month": "2026-12", "target_price": 4.50, "increment_bushels": 5000}, ADVISOR))
        # Default logical clock is 2026-05-01; the QUOTE tick fires the target.
        record_quote_tick(4.60, "2026-05-01")
        fired = get_success_data(api.get_price_target(target["id"], ADVISOR))
        assert fired["status"] == "TRIGGERED"
        rec_id = fired["recommendation_id"]
        set_logical_clock("2026-05-10T00:00:00Z")
        record_quote_tick(4.61, "2026-05-10")
        rec = get_success_data(api.get_recommendation(rec_id, ADVISOR))
        assert rec["status"] == "EXPIRED", "a proposal older than five days must expire on the next tick sweep"
        target_after = get_success_data(api.get_price_target(target["id"], ADVISOR))
        assert target_after["status"] == "LAPSED", "expiry must lapse the originating target"
        plan = get_success_data(api.get_plan(plan_id, ADVISOR))
        assert plan["pending_recommendation_count"] == 0, "expiry must decrement the pending count back to 0"

    def test_target_double_cancel_rejected(self, api):
        """PRD §3.3: "The advisor may cancel a pending target, moving it from
        `PENDING` to `CANCELLED`."
        PRD §2.6: "Sixth, the target resource must be in a from-state that
        permits the requested transition, producing `ERR_INVALID_STATE`."

        Design: Corner/state_machines/target_double_cancel_rejected
        """
        ctx = setup_operation_with_active_plan(
            name="Idem Farm", risk_profile="BALANCED", max_priced_pct=0.80
        )
        target = get_success_data(api.create_price_target(
            {"plan_id": ctx["plan"]["id"], "contract_month": "2026-12",
             "target_price": 4.80, "increment_bushels": 2000}, ADVISOR))
        first = get_success_data(api.cancel_price_target(target["id"], ADVISOR))
        assert first["status"] == "CANCELLED"
        resp = api.cancel_price_target(target["id"], ADVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
