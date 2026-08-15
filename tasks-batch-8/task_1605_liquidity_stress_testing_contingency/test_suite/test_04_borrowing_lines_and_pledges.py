"""Borrowing power, pledge/release, draw/repay, suspension cascades.

Difficulty instances: borrowing_power_pinned_evaluation_order,
pledge_release_roundtrip_conserves_line_capacity_fields,
draw_repay_roundtrip_conserves_drawn_balance,
pledge_release_cascades_to_line_suspension_and_action_block,
draw_suspended_line_safety_beats_power_fiscal,
pledge_creation_gated_by_asset_encumbrance.
Corner instances: draw_response_reflects_mutation_immediately,
repay_exceeding_drawn_rejected, draw_above_borrowing_power_rejected,
reinstate_suspended_line_restores_blocked_actions.
"""
from test_helpers import (
    ApiErrorId,
    assert_borrowing_line,
    assert_borrowing_power_invariants,
    draw_payload,
    make_asset,
    make_line,
    make_pledge,
    make_scenario,
    repay_payload,
    setup_active_drawdown_playbook,
    setup_line_with_pledge,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


class TestBorrowingPowerPinnedOrder:
    def test_borrowing_power_pledge_cap_floor(self, api, ops_headers):
        """PRD §3.4: "First, sum the `pledged_value_cents` of the line's
        `ACTIVE` pledges into the line's pledged total."
        PRD §3.4: "Second, compute the collateral cap as that pledged total
        times the line's `advance_rate_bps`, divided by ten thousand and
        rounded down to whole cents — the floor happens at this step."
        PRD §3.4: "Third, set `borrowing_power_cents` to the smaller of
        `total_capacity_cents` and the collateral cap, minus `drawn_cents`, but
        never below zero."
        PRD §3.3: "a pledge's `pledged_value_cents` is pinned once, at pledge
        creation, to the BASELINE-variant adjusted value of the asset".

        Design: Difficulty/combinatorial_formula/borrowing_power_pinned_evaluation_order
        """
        line = make_line(provider_name="FHLB", line_type="FHLB",
                         total_capacity_cents=80_000_000, advance_rate_bps=5000)
        asset = make_asset(asset_class="LEVEL_2A", reference="A1",
                           market_value_cents=100_000_000)
        pledge = make_pledge(asset["id"], line["id"])
        # Pinned at creation: floor(100000000 * (10000 - 1500) / 10000) = 85000000.
        assert pledge["pledged_value_cents"] == 85_000_000, (
            f"pledged_value_cents must pin to 85000000, got {pledge['pledged_value_cents']}"
        )
        line_now = validate_success(api.get_borrowing_line(line["id"], ops_headers))
        assert_borrowing_line(line_now)
        assert line_now["pledged_value_cents"] == 85_000_000
        # min(80000000, floor(85000000 * 0.5)) - 0 = 42500000.
        assert line_now["borrowing_power_cents"] == 42_500_000, (
            f"power must be 42500000, got {line_now['borrowing_power_cents']}"
        )
        assert_borrowing_power_invariants(line_now)

    def test_draw_at_exactly_full_power_permitted(self, api, ops_headers):
        """PRD §3.4: "A draw requires the line `ACTIVE` (`ERR_LINE_SUSPENDED`)
        and a positive amount not exceeding the current `borrowing_power_cents`
        — drawing exactly the full power is permitted — with violations
        rejected as `ERR_INSUFFICIENT_BORROWING_POWER`; the amount is added to
        `drawn_cents` and power recomputes."
        PRD §3.4: "Third, set `borrowing_power_cents` to the smaller of
        `total_capacity_cents` and the collateral cap, minus `drawn_cents`, but
        never below zero."

        Design: Difficulty/combinatorial_formula/borrowing_power_pinned_evaluation_order
        """
        line, asset, _pledge = setup_line_with_pledge(
            total_capacity_cents=80_000_000, advance_rate_bps=5000,
            asset_class="LEVEL_2A", market_value_cents=100_000_000,
        )
        # Power is exactly 42500000; drawing the full power is permitted.
        resp = api.draw_borrowing_line(line["id"], draw_payload(amount_cents=42_500_000), ops_headers)
        after = validate_success(resp)
        assert after["drawn_cents"] == 42_500_000, f"drawn must be 42500000, got {after['drawn_cents']}"
        assert after["borrowing_power_cents"] == 0, (
            f"power floors at zero after a full draw, got {after['borrowing_power_cents']}"
        )


class TestPledgeReleaseRoundtrip:
    def test_pledge_release_roundtrip_conserves_capacity_fields(self, api, ops_headers):
        """PRD §3.4: "A successful pledge pins its `pledged_value_cents` per
        §3.3, flips the asset `UNENCUMBERED` → `PLEDGED`, starts the pledge
        itself `ACTIVE`, and triggers a line recompute. Release flips the
        pledge `ACTIVE` → `RELEASED`, returns the referenced asset to
        `UNENCUMBERED`, and recomputes the line once more".
        PRD §3.3: "An asset's `encumbrance_status` cycles `UNENCUMBERED` →
        `PLEDGED` when a pledge referencing it is created, and returns
        `PLEDGED` → `UNENCUMBERED` when that pledge is released."

        Design: Difficulty/compensating_invariant/pledge_release_roundtrip_conserves_line_capacity_fields
        """
        line = make_line(provider_name="FHLB", line_type="FHLB",
                         total_capacity_cents=80_000_000, advance_rate_bps=5000)
        asset = make_asset(asset_class="LEVEL_2A", reference="A1",
                           market_value_cents=100_000_000)
        before = validate_success(api.get_borrowing_line(line["id"], ops_headers))
        assert before["pledged_value_cents"] == 0
        assert before["borrowing_power_cents"] == 0
        assert before["drawn_cents"] == 0

        pledge = make_pledge(asset["id"], line["id"])
        assert pledge["pledged_value_cents"] == 85_000_000
        during = validate_success(api.get_borrowing_line(line["id"], ops_headers))
        assert during["borrowing_power_cents"] == 42_500_000

        released = validate_success(api.release_collateral_pledge(pledge["id"], ops_headers))
        assert released["status"] == "RELEASED"

        after = validate_success(api.get_borrowing_line(line["id"], ops_headers))
        assert after["pledged_value_cents"] == before["pledged_value_cents"] == 0
        assert after["borrowing_power_cents"] == before["borrowing_power_cents"] == 0
        assert after["drawn_cents"] == before["drawn_cents"] == 0

        assets, _meta = validate_paginated(
            api.list_liquid_assets(ops_headers, params={"asset_class": "LEVEL_2A"})
        )
        assert assets[0]["encumbrance_status"] == "UNENCUMBERED", (
            f"release must return the asset to UNENCUMBERED, got {assets[0]['encumbrance_status']}"
        )
        pledge_now = validate_success(api.get_collateral_pledge(pledge["id"], ops_headers))
        assert pledge_now["status"] == "RELEASED"

    def test_pledge_pins_value_against_later_reprice(self, api, ops_headers):
        """PRD §3.3: "One figure is immune to repricing: a pledge's
        `pledged_value_cents` is pinned once, at pledge creation, to the
        BASELINE-variant adjusted value of the asset — that is, with the add-on
        at zero — and is never re-priced afterward, whatever the market does."

        Design: Difficulty/compensating_invariant/pledge_release_roundtrip_conserves_line_capacity_fields
        """
        line, asset, pledge = setup_line_with_pledge(
            total_capacity_cents=80_000_000, advance_rate_bps=5000,
            asset_class="LEVEL_2A", market_value_cents=100_000_000,
        )
        assert pledge["pledged_value_cents"] == 85_000_000
        # Reprice the asset; the pinned pledge value must not move.
        validate_success(api.reprice_liquid_asset(
            asset["id"], {"market_value_cents": 50_000_000}, ops_headers,
        ))
        pledge_now = validate_success(api.get_collateral_pledge(pledge["id"], ops_headers))
        assert pledge_now["pledged_value_cents"] == 85_000_000, (
            f"pinned pledge value must survive repricing, got {pledge_now['pledged_value_cents']}"
        )
        line_now = validate_success(api.get_borrowing_line(line["id"], ops_headers))
        assert line_now["pledged_value_cents"] == 85_000_000


class TestDrawRepayRoundtrip:
    def test_draw_repay_roundtrip_conserves_drawn_balance(self, api, ops_headers):
        """PRD §3.4: "the amount is added to `drawn_cents` and power
        recomputes. A repayment must be positive and no larger than the current
        `drawn_cents` (`ERR_REPAY_EXCEEDS_DRAWN`); it reduces the drawn balance
        and likewise recomputes power."

        Design: Difficulty/compensating_invariant/draw_repay_roundtrip_conserves_drawn_balance
        """
        line, _asset, _pledge = setup_line_with_pledge(
            total_capacity_cents=80_000_000, advance_rate_bps=5000,
            asset_class="LEVEL_2A", market_value_cents=100_000_000,
        )
        # Pre-draw: power 42500000, drawn 0.
        drawn_resp = validate_success(
            api.draw_borrowing_line(line["id"], draw_payload(amount_cents=30_000_000), ops_headers)
        )
        assert drawn_resp["drawn_cents"] == 30_000_000
        assert drawn_resp["borrowing_power_cents"] == 12_500_000, (
            f"42500000 - 30000000 = 12500000, got {drawn_resp['borrowing_power_cents']}"
        )
        repaid_resp = validate_success(
            api.repay_borrowing_line(line["id"], repay_payload(amount_cents=30_000_000), ops_headers)
        )
        assert repaid_resp["drawn_cents"] == 0, f"drawn must return to 0, got {repaid_resp['drawn_cents']}"
        assert repaid_resp["borrowing_power_cents"] == 42_500_000, (
            f"power must return to 42500000, got {repaid_resp['borrowing_power_cents']}"
        )

    def test_repeated_draw_repay_cycles_leave_no_drift(self, api, ops_headers):
        """PRD §3.4: "the amount is added to `drawn_cents` and power
        recomputes. A repayment must be positive and no larger than the current
        `drawn_cents` (`ERR_REPAY_EXCEEDS_DRAWN`); it reduces the drawn balance
        and likewise recomputes power."
        PRD §3.4: "Third, set `borrowing_power_cents` to the smaller of
        `total_capacity_cents` and the collateral cap, minus `drawn_cents`, but
        never below zero."

        Design: Difficulty/compensating_invariant/draw_repay_roundtrip_conserves_drawn_balance
        """
        line, _asset, _pledge = setup_line_with_pledge(
            total_capacity_cents=80_000_000, advance_rate_bps=5000,
            asset_class="LEVEL_2A", market_value_cents=100_000_000,
        )
        # Two compensating cycles: the drawn balance and headroom return
        # bit-identical to the pre-draw values after each cycle.
        for _ in range(2):
            validate_success(api.draw_borrowing_line(
                line["id"], draw_payload(amount_cents=30_000_000), ops_headers,
            ))
            validate_success(api.repay_borrowing_line(
                line["id"], repay_payload(amount_cents=30_000_000), ops_headers,
            ))
            line_now = validate_success(api.get_borrowing_line(line["id"], ops_headers))
            assert line_now["drawn_cents"] == 0
            assert line_now["borrowing_power_cents"] == 42_500_000, (
                f"no drift after the cycle, got {line_now['borrowing_power_cents']}"
            )

    def test_draw_response_reflects_mutation_immediately(self, api, ops_headers):
        """PRD §2.10: "Every request's side effects apply atomically within
        that request: either the entire cascade lands or the request fails,
        with nothing left partially applied."
        PRD §2.10: "Implementations must not defer any of these effects to
        background processing."
        PRD §3.4: "The derived figure is recomputed on every pledge, release,
        draw, repayment, drawdown execution, and drawdown failure, and is what
        reads of the line return."

        Design: Corner/consistency_model/draw_response_reflects_mutation_immediately
        """
        line, _asset, _pledge = setup_line_with_pledge(
            total_capacity_cents=80_000_000, advance_rate_bps=5000,
            asset_class="LEVEL_2A", market_value_cents=100_000_000,
        )
        drawn_resp = validate_success(
            api.draw_borrowing_line(line["id"], draw_payload(amount_cents=30_000_000), ops_headers)
        )
        assert drawn_resp["drawn_cents"] == 30_000_000
        assert drawn_resp["borrowing_power_cents"] == 12_500_000
        read_back = validate_success(api.get_borrowing_line(line["id"], ops_headers))
        assert read_back["drawn_cents"] == drawn_resp["drawn_cents"] == 30_000_000
        assert read_back["borrowing_power_cents"] == drawn_resp["borrowing_power_cents"] == 12_500_000


class TestPledgeReleaseCascade:
    def test_pledge_release_suspends_line_and_blocks_action(self, api, ops_headers):
        """PRD §3.4: "Release flips the pledge `ACTIVE` → `RELEASED`, returns
        the referenced asset to `UNENCUMBERED`, and recomputes the line once
        more — and this is where the cascade bites: if the recompute leaves
        `drawn_cents` above the smaller of total capacity and collateral cap
        while the line is still `ACTIVE`, the line suspends itself, and every
        `PENDING` or `READY` drawdown action referencing it becomes `BLOCKED`
        in the same request."

        Design: Difficulty/transitive_cascade/pledge_release_cascades_to_line_suspension_and_action_block
        """
        ctx = setup_active_drawdown_playbook(
            target_capacity_cents=5_000_000,
            draw_amount_cents=5_000_000,
            line_capacity_cents=50_000_000,
            advance_rate_bps=10_000,
            pledged_asset_value_cents=60_000_000,
        )
        line = ctx["line"]
        action = ctx["action"]
        pledge = ctx["pledge"]
        asset = ctx["asset"]
        # Draw 40000000: drawn 40000000, power 10000000.
        validate_success(api.draw_borrowing_line(line["id"], draw_payload(amount_cents=40_000_000), ops_headers))

        released = validate_success(api.release_collateral_pledge(pledge["id"], ops_headers))
        assert released["status"] == "RELEASED"

        line_now = validate_success(api.get_borrowing_line(line["id"], ops_headers))
        assert line_now["pledged_value_cents"] == 0
        assert line_now["borrowing_power_cents"] == 0
        assert line_now["status"] == "SUSPENDED", (
            f"drawn 40000000 > min(50000000, 0) = 0 after recompute must suspend the line, "
            f"got {line_now['status']}"
        )

        action_now = validate_success(api.get_playbook_action(action["id"], ops_headers))
        assert action_now["status"] == "BLOCKED", (
            f"the READY drawdown action must become BLOCKED in the same request, got {action_now['status']}"
        )

        assets, _meta = validate_paginated(
            api.list_liquid_assets(ops_headers, params={"encumbrance_status": "UNENCUMBERED"})
        )
        assert any(a["id"] == asset["id"] for a in assets), (
            "the released asset must return to UNENCUMBERED"
        )

    def test_blocked_action_rejects_execution_while_line_suspended(self, api, ops_headers):
        """PRD §3.4: "if the recompute leaves `drawn_cents` above the smaller
        of total capacity and collateral cap while the line is still `ACTIVE`,
        the line suspends itself, and every `PENDING` or `READY` drawdown
        action referencing it becomes `BLOCKED` in the same request."
        PRD §3.9: "A `LINE_DRAWDOWN` requires its line `ACTIVE`
        (`ERR_LINE_SUSPENDED` otherwise)".

        Design: Difficulty/transitive_cascade/pledge_release_cascades_to_line_suspension_and_action_block
        """
        ctx = setup_active_drawdown_playbook(
            target_capacity_cents=5_000_000,
            draw_amount_cents=5_000_000,
            line_capacity_cents=50_000_000,
            advance_rate_bps=10_000,
            pledged_asset_value_cents=60_000_000,
        )
        line = ctx["line"]
        action = ctx["action"]
        pledge = ctx["pledge"]
        validate_success(api.draw_borrowing_line(line["id"], draw_payload(amount_cents=40_000_000), ops_headers))
        validate_success(api.release_collateral_pledge(pledge["id"], ops_headers))

        resp = api.execute_playbook_action(action["id"], ops_headers)
        # The action is BLOCKED (not READY) and the line SUSPENDED; both
        # surfaces reject the execution. The PRD pins the line-availability
        # error explicitly; the state gate is the alternative named surface.
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_LINE_SUSPENDED],
        )


class TestLineSuspensionGuards:
    def test_draw_suspended_line_safety_beats_power_fiscal(self, api, officer_headers, ops_headers):
        """PRD §2.9: "Validation runs in a fixed order so that a request
        failing several checks always surfaces the earliest failure."
        PRD §2.9: "Seventh, business-safety gates: segregation of duties
        (`ERR_SOD_VIOLATION`), posture sufficiency (`ERR_POSTURE_INSUFFICIENT`),
        line availability (`ERR_LINE_SUSPENDED`), asset availability
        (`ERR_ASSET_NOT_PLEDGEABLE`, `ERR_ASSET_NOT_AVAILABLE`), scenario
        status (`ERR_SCENARIO_RETIRED`), and de-escalation conditions
        (`ERR_DEESCALATION_BLOCKED`)."
        PRD §2.9: "Tenth and last, fiscal bounds
        (`ERR_INSUFFICIENT_BORROWING_POWER`, `ERR_REPAY_EXCEEDS_DRAWN`)."
        PRD §3.4: "A draw requires the line `ACTIVE` (`ERR_LINE_SUSPENDED`)".

        Design: Difficulty/priority_pair_validation_conflict/draw_suspended_line_safety_beats_power_fiscal
        """
        line = make_line(provider_name="RepoCo", line_type="REPO",
                         total_capacity_cents=10_000_000, advance_rate_bps=10_000)
        # No pledges: borrowing power is 0. Suspend the line manually.
        validate_success(api.suspend_borrowing_line(line["id"], officer_headers))
        # The 5000000 draw exceeds the zero power AND the line is suspended;
        # the earlier (line availability) failure must surface.
        resp = api.draw_borrowing_line(line["id"], draw_payload(amount_cents=5_000_000), ops_headers)
        validate_error(resp, ApiErrorId.ERR_LINE_SUSPENDED)

    def test_draw_on_suspended_line_with_power_still_reports_suspension(self, api, officer_headers, ops_headers):
        """PRD §2.9: "Seventh, business-safety gates: segregation of duties
        (`ERR_SOD_VIOLATION`), posture sufficiency (`ERR_POSTURE_INSUFFICIENT`),
        line availability (`ERR_LINE_SUSPENDED`), asset availability
        (`ERR_ASSET_NOT_PLEDGEABLE`, `ERR_ASSET_NOT_AVAILABLE`), scenario
        status (`ERR_SCENARIO_RETIRED`), and de-escalation conditions
        (`ERR_DEESCALATION_BLOCKED`)."
        PRD §2.9: "Tenth and last, fiscal bounds
        (`ERR_INSUFFICIENT_BORROWING_POWER`, `ERR_REPAY_EXCEEDS_DRAWN`)."
        PRD §3.4: "A draw requires the line `ACTIVE` (`ERR_LINE_SUSPENDED`) and
        a positive amount not exceeding the current `borrowing_power_cents`".

        Design: Difficulty/priority_pair_validation_conflict/draw_suspended_line_safety_beats_power_fiscal
        """
        # Line WITH pledged collateral (nonzero power) and a draw amount that
        # exceeds it — the suspended-line gate still surfaces first.
        line, _asset, _pledge = setup_line_with_pledge(
            total_capacity_cents=80_000_000, advance_rate_bps=5000,
            asset_class="LEVEL_2A", market_value_cents=100_000_000,
        )
        validate_success(api.suspend_borrowing_line(line["id"], officer_headers))
        resp = api.draw_borrowing_line(line["id"], draw_payload(amount_cents=42_500_001), ops_headers)
        validate_error(resp, ApiErrorId.ERR_LINE_SUSPENDED)

    def test_reinstate_restores_blocked_action_to_ready(self, api, officer_headers, ops_headers):
        """PRD §3.4: "A `RiskOfficer` can also suspend an `ACTIVE` line
        manually, producing the same blocking cascade, and can later reinstate
        a `SUSPENDED` line — but only while the drawn balance sits within the
        smaller of total capacity and collateral cap, failing which the request
        is rejected with `ERR_INVALID_STATE`."
        PRD §3.4: "Reinstatement wakes the line's `BLOCKED` actions: each
        returns to `READY` when its playbook is `ACTIVATED` or `EXECUTING`, and
        to `PENDING` otherwise."

        Design: Corner/state_machines/reinstate_suspended_line_restores_blocked_actions
        """
        ctx = setup_active_drawdown_playbook(
            target_capacity_cents=5_000_000,
            draw_amount_cents=5_000_000,
            line_capacity_cents=50_000_000,
            advance_rate_bps=10_000,
            pledged_asset_value_cents=60_000_000,
        )
        line = ctx["line"]
        action = ctx["action"]

        validate_success(api.suspend_borrowing_line(line["id"], officer_headers))
        blocked = validate_success(api.get_playbook_action(action["id"], ops_headers))
        assert blocked["status"] == "BLOCKED", f"suspend cascade must block the action, got {blocked['status']}"

        reinstated = validate_success(api.reinstate_borrowing_line(line["id"], officer_headers))
        assert reinstated["status"] == "ACTIVE"

        ready = validate_success(api.get_playbook_action(action["id"], ops_headers))
        assert ready["status"] == "READY", (
            f"reinstatement must return the BLOCKED action to READY (playbook ACTIVATED), "
            f"got {ready['status']}"
        )
        executed = validate_success(api.execute_playbook_action(action["id"], ops_headers))
        assert executed["status"] == "EXECUTING"


class TestPledgeCreationGate:
    def test_pledge_creation_gated_by_asset_encumbrance(self, api, ops_headers):
        """PRD §3.4: "Pledging is a `TreasuryOps` act supplying `asset_id` and
        `line_id`. The asset must be `UNENCUMBERED` (`ERR_ASSET_NOT_PLEDGEABLE`
        otherwise) and the line must be `ACTIVE` (`ERR_LINE_SUSPENDED`
        otherwise)."
        PRD §3.3: "An asset's `encumbrance_status` cycles `UNENCUMBERED` →
        `PLEDGED` when a pledge referencing it is created".

        Design: Difficulty/cross_entity_state_dependency/pledge_creation_gated_by_asset_encumbrance
        """
        line1 = make_line(provider_name="Fed", line_type="FED_DISCOUNT_WINDOW",
                          total_capacity_cents=30_000_000, advance_rate_bps=10_000)
        line2 = make_line(provider_name="FHLB", line_type="FHLB",
                          total_capacity_cents=30_000_000, advance_rate_bps=10_000)
        asset = make_asset(asset_class="LEVEL_1", reference="A1",
                           market_value_cents=30_000_000)
        first = make_pledge(asset["id"], line1["id"])
        assert first["status"] == "ACTIVE"
        # LEVEL_1 haircut is zero, so the pin equals the market value.
        assert first["pledged_value_cents"] == 30_000_000

        resp = api.create_collateral_pledge(
            {"asset_id": asset["id"], "line_id": line2["id"]}, ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ASSET_NOT_PLEDGEABLE)

    def test_pledge_after_release_succeeds_again(self, api, ops_headers):
        """PRD §3.3: "An asset's `encumbrance_status` cycles `UNENCUMBERED` →
        `PLEDGED` when a pledge referencing it is created, and returns
        `PLEDGED` → `UNENCUMBERED` when that pledge is released."
        PRD §3.4: "The asset must be `UNENCUMBERED` (`ERR_ASSET_NOT_PLEDGEABLE`
        otherwise)".

        Design: Difficulty/cross_entity_state_dependency/pledge_creation_gated_by_asset_encumbrance
        """
        line = make_line(provider_name="Fed", total_capacity_cents=30_000_000,
                         advance_rate_bps=10_000)
        asset = make_asset(asset_class="LEVEL_1", reference="A1",
                           market_value_cents=30_000_000)
        first = make_pledge(asset["id"], line["id"])
        resp = api.create_collateral_pledge({"asset_id": asset["id"], "line_id": line["id"]}, ops_headers)
        validate_error(resp, ApiErrorId.ERR_ASSET_NOT_PLEDGEABLE)
        validate_success(api.release_collateral_pledge(first["id"], ops_headers))
        # After release the asset is UNENCUMBERED again, so a fresh pledge succeeds.
        second = make_pledge(asset["id"], line["id"])
        assert second["status"] == "ACTIVE"
        assert second["pledged_value_cents"] == 30_000_000


class TestFiscalBounds:
    def test_repay_exceeding_drawn_rejected(self, api, ops_headers):
        """PRD §3.4: "A repayment must be positive and no larger than the
        current `drawn_cents` (`ERR_REPAY_EXCEEDS_DRAWN`)".

        Design: Corner/validations/repay_exceeding_drawn_rejected
        """
        line = make_line(provider_name="RepoCo", line_type="REPO",
                         total_capacity_cents=10_000_000, advance_rate_bps=10_000)
        resp = api.repay_borrowing_line(line["id"], repay_payload(amount_cents=1), ops_headers)
        validate_error(resp, ApiErrorId.ERR_REPAY_EXCEEDS_DRAWN)

    def test_draw_above_borrowing_power_rejected(self, api, ops_headers):
        """PRD §3.4: "A draw requires the line `ACTIVE` (`ERR_LINE_SUSPENDED`)
        and a positive amount not exceeding the current `borrowing_power_cents`
        — drawing exactly the full power is permitted — with violations
        rejected as `ERR_INSUFFICIENT_BORROWING_POWER`; the amount is added to
        `drawn_cents` and power recomputes."

        Design: Corner/validations/draw_above_borrowing_power_rejected
        """
        line, _asset, _pledge = setup_line_with_pledge(
            total_capacity_cents=80_000_000, advance_rate_bps=5000,
            asset_class="LEVEL_2A", market_value_cents=100_000_000,
        )
        # Power is exactly 42500000; one cent over must be rejected.
        resp = api.draw_borrowing_line(line["id"], draw_payload(amount_cents=42_500_001), ops_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BORROWING_POWER)
