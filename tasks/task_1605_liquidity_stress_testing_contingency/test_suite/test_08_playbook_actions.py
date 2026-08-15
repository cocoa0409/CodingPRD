"""Playbook action execution: settlement timing, prerequisites, compensation.

Corner instances: settle_before_lag_then_at_boundary,
execute_with_unsettled_prerequisite_rejected,
stand_down_with_executing_action_rejected,
complete_with_executing_action_rejected,
execute_sale_of_pledged_asset_rejected,
fail_executing_drawdown_compensates_draw.
"""
from test_helpers import (
    ApiErrorId,
    add_action,
    build_user_headers,
    create_playbook_payload,
    make_activated_playbook,
    make_analyst_headers,
    make_asset,
    make_committee_headers,
    make_line,
    make_officer_headers,
    make_ops_headers,
    make_playbook,
    make_pledge,
    make_scenario,
    setup_executing_drawdown,
    setup_line_with_pledge,
    validate_error,
    validate_success,
)

ANALYST = make_analyst_headers("ta_1")
OFFICER = make_officer_headers("ro_1")
COMMITTEE = make_committee_headers("lc_1")
OPS = make_ops_headers("to_1")
ADMIN = build_user_headers("pa_1", "PlatformAdmin")


class TestSettlementTiming:
    def test_settle_before_lag_then_at_boundary(self, api, ops_headers, admin_headers):
        """PRD §3.9: "Settlement requires the logical clock to have reached
        `executed_at` plus the action's `settlement_lag_days` — landing exactly
        on that instant counts as due — and an early attempt is rejected with
        `ERR_SETTLEMENT_NOT_DUE`".
        PRD §2.4: "Before the clock has ever been set, it reads exactly
        2026-08-01T00:00:00Z, and it never falls back to wall-clock time
        afterward. A `PlatformAdmin`-only test-driving capability advances the
        logical clock to a supplied `to_iso8601` instant".

        Design: Corner/state_machines/settle_before_lag_then_at_boundary
        """
        ctx = setup_executing_drawdown(
            target_capacity_cents=1_000_000, draw_amount_cents=1_000_000,
            settlement_lag_days=2,
        )
        action_id = ctx["action"]["id"]
        # The clock still reads 2026-08-01T00:00:00Z: two days short of due.
        resp = api.settle_playbook_action(action_id, ops_headers)
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_DUE)

        # Advance exactly to executed_at + 2 days: the boundary counts as due.
        validate_success(api.set_clock({"to_iso8601": "2026-08-03T00:00:00Z"}, admin_headers))
        settled = validate_success(api.settle_playbook_action(action_id, ops_headers))
        assert settled["status"] == "SETTLED", f"got {settled['status']}"


class TestPrerequisiteEnforcement:
    def test_execute_with_unsettled_prerequisite_rejected(self, api, ops_headers):
        """PRD §3.9: "Prerequisites are enforced at execute time: an action
        naming a `prerequisite_action_id` cannot execute until that
        prerequisite stands `SETTLED`, failing which the request is rejected
        with `ERR_PREREQUISITE_ACTION_INCOMPLETE`."

        Design: Corner/state_machines/execute_with_unsettled_prerequisite_rejected
        """
        scenario = make_scenario(name="Base", tier="BASELINE")
        line, _asset, _pledge = setup_line_with_pledge()
        playbook = make_playbook(scenario["id"], name="PB",
                                 target_capacity_cents=50_000_000)
        action1 = add_action(playbook["id"], kind="LINE_DRAWDOWN", sequence_no=1,
                             estimated_proceeds_cents=30_000_000, settlement_lag_days=0,
                             line_id=line["id"])
        action2 = add_action(playbook["id"], kind="LINE_DRAWDOWN", sequence_no=2,
                             estimated_proceeds_cents=20_000_000, settlement_lag_days=0,
                             line_id=line["id"], prerequisite_action_id=action1["id"])
        # Per-line aggregate 50000000 <= power 100000000 -> PASSED.
        result = validate_success(api.run_capacity_test(playbook["id"], OFFICER))
        assert result["result"] == "PASSED"
        validate_success(api.approve_playbook(playbook["id"], make_officer_headers("ro_2")))
        validate_success(api.activate_playbook(playbook["id"], COMMITTEE))

        # action2 is READY but its prerequisite is not SETTLED.
        resp = api.execute_playbook_action(action2["id"], ops_headers)
        validate_error(resp, ApiErrorId.ERR_PREREQUISITE_ACTION_INCOMPLETE)

        validate_success(api.execute_playbook_action(action1["id"], ops_headers))
        settled1 = validate_success(api.settle_playbook_action(action1["id"], ops_headers))
        assert settled1["status"] == "SETTLED"

        executed2 = validate_success(api.execute_playbook_action(action2["id"], ops_headers))
        assert executed2["status"] == "EXECUTING", (
            f"with the prerequisite SETTLED the dependent action executes, got {executed2['status']}"
        )


class TestStandDownAndCompleteGates:
    def test_stand_down_with_executing_action_rejected(self, api, committee_headers, ops_headers):
        """PRD §3.9: "Stand-down, a `LiquidityCommittee` act from `ACTIVATED`
        or `EXECUTING`, is refused while any action of the playbook stands
        `EXECUTING` (`ERR_INVALID_STATE`); otherwise the playbook moves to
        `STOOD_DOWN`".

        Design: Corner/state_machines/stand_down_with_executing_action_rejected
        """
        ctx = setup_executing_drawdown(
            target_capacity_cents=1_000_000, draw_amount_cents=1_000_000,
            settlement_lag_days=0,
        )
        resp = api.stand_down_playbook(ctx["playbook"]["id"], committee_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        settled = validate_success(api.settle_playbook_action(ctx["action"]["id"], ops_headers))
        assert settled["status"] == "SETTLED"
        stood_down = validate_success(api.stand_down_playbook(ctx["playbook"]["id"], committee_headers))
        assert stood_down["status"] == "STOOD_DOWN", (
            f"once no action stands EXECUTING the stand-down succeeds, got {stood_down['status']}"
        )

    def test_complete_with_executing_action_rejected(self, api, committee_headers):
        """PRD §3.9: "Completion, a `LiquidityCommittee` act from `EXECUTING`,
        requires every action of the playbook to stand in a terminal state —
        `SETTLED`, `FAILED`, or `SKIPPED` — with stragglers earning
        `ERR_ACTIONS_NOT_ALL_TERMINAL`".

        Design: Corner/validations/complete_with_executing_action_rejected
        """
        ctx = setup_executing_drawdown(
            target_capacity_cents=1_000_000, draw_amount_cents=1_000_000,
            settlement_lag_days=0,
        )
        playbook_now = validate_success(api.get_playbook(ctx["playbook"]["id"], ANALYST))
        assert playbook_now["status"] == "EXECUTING"
        resp = api.complete_playbook(ctx["playbook"]["id"], committee_headers)
        validate_error(resp, ApiErrorId.ERR_ACTIONS_NOT_ALL_TERMINAL)


class TestExecuteAssetSaleGate:
    def test_execute_sale_of_pledged_asset_rejected(self, api, ops_headers):
        """PRD §3.9: "An `ASSET_SALE` requires its referenced asset to be
        `UNENCUMBERED` (`ERR_ASSET_NOT_AVAILABLE` otherwise) and marks the
        asset `SOLD`."
        PRD §3.3: "An asset's `encumbrance_status` cycles `UNENCUMBERED` →
        `PLEDGED` when a pledge referencing it is created".

        Design: Corner/validations/execute_sale_of_pledged_asset_rejected
        """
        scenario = make_scenario(name="Base", tier="BASELINE")
        line = make_line(total_capacity_cents=100_000_000, advance_rate_bps=10_000)
        sale_asset = make_asset(asset_class="LEVEL_1", reference="S1",
                                market_value_cents=50_000_000)
        playbook = make_playbook(scenario["id"], name="PB",
                                 target_capacity_cents=40_000_000)
        action = add_action(playbook["id"], kind="ASSET_SALE", sequence_no=1,
                            estimated_proceeds_cents=40_000_000, settlement_lag_days=0,
                            asset_id=sale_asset["id"])
        # Asset UNENCUMBERED at test time: cap 50000000 >= 40000000.
        result = validate_success(api.run_capacity_test(playbook["id"], OFFICER))
        assert result["result"] == "PASSED", f"got {result['result']}"
        validate_success(api.approve_playbook(playbook["id"], make_officer_headers("ro_2")))
        # The asset is pledged after the capacity test: PLEDGED by execution time.
        make_pledge(sale_asset["id"], line["id"])
        validate_success(api.activate_playbook(playbook["id"], COMMITTEE))

        resp = api.execute_playbook_action(action["id"], ops_headers)
        validate_error(resp, ApiErrorId.ERR_ASSET_NOT_AVAILABLE)


class TestFailCompensation:
    def test_fail_executing_drawdown_compensates_draw(self, api, ops_headers):
        """PRD §3.9: "Failing an `EXECUTING` action marks it `FAILED`, and for
        a drawdown the failure compensates the booking: the proceeds come back
        off the line's `drawn_cents` and borrowing power recomputes, because
        the funds never arrived."

        Design: Corner/state_machines/fail_executing_drawdown_compensates_draw
        """
        ctx = setup_executing_drawdown(
            target_capacity_cents=10_000_000, draw_amount_cents=10_000_000,
            settlement_lag_days=0,
        )
        line_id = ctx["line"]["id"]
        during = validate_success(api.get_borrowing_line(line_id, ops_headers))
        assert during["drawn_cents"] == 10_000_000
        assert during["borrowing_power_cents"] == 90_000_000

        failed = validate_success(api.fail_playbook_action(ctx["action"]["id"], ops_headers))
        assert failed["status"] == "FAILED"

        after = validate_success(api.get_borrowing_line(line_id, ops_headers))
        assert after["drawn_cents"] == 0, (
            f"the compensated draw must leave drawn_cents at 0, got {after['drawn_cents']}"
        )
        assert after["borrowing_power_cents"] == 100_000_000, (
            f"power must return to its pre-execution value 100000000, got {after['borrowing_power_cents']}"
        )
