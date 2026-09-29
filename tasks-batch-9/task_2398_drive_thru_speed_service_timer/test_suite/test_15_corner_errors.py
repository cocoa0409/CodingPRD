"""Error identity: the right code, from the right rung of the priority ladder.

The point of each test is discrimination — the neighbouring rule that could
plausibly have fired is shown not to fire.
"""

from prd_bench_local_runner.testing import (
    build_user_headers,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import DriveThruApiClient
from test_helpers.api_errors import (
    ERR_COACHING_NOT_FOUND,
    ERR_DEPLOYMENT_BUFFER_VIOLATION,
    ERR_DEPLOYMENT_NOT_FOUND,
    ERR_INCIDENT_NOT_FOUND,
    ERR_INVALID_COACHING_STATE,
    ERR_INVALID_OVERRIDE_STATE,
    ERR_INVALID_PULL_FORWARD_STATE,
    ERR_INVALID_REPORT_STATE,
    ERR_INVALID_SLOT_STATE,
    ERR_LABOR_BUDGET_EXCEEDED,
    ERR_LOOP_NOT_FOUND,
    ERR_LOOP_NOT_MERGEABLE,
    ERR_OVERRIDE_AGGREGATE_CAP,
    ERR_OVERRIDE_NOT_FOUND,
    ERR_PROFILE_NOT_ACTIVE,
    ERR_PROFILE_NOT_FOUND,
    ERR_PULL_FORWARD_NOT_FOUND,
    ERR_REPORT_NOT_FOUND,
    ERR_REPORT_WINDOW_EMPTY,
    ERR_RESTAURANT_MISMATCH,
    ERR_RESTAURANT_NOT_FOUND,
    ERR_SLOT_NOT_FOUND,
    ERR_STAFF_NOT_AVAILABLE,
    ERR_STAFF_NOT_OOT_CERTIFIED,
    ERR_STAFF_SCOPE_MISMATCH,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.constants import ABSENT_UUID
from test_helpers.test_users import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    COACH_HEADERS,
    ROLE_SHIFT_LEADER,
    UNKNOWN_ROLE,
    headers_without_user_id,
)


class TestTypedPathNotFound:
    """Eleven declared 404 codes, not one generic one."""

    def test_each_action_path_answers_with_its_own_not_found_code(
        self, api: DriveThruApiClient
    ):
        """PRD §2.11: "**Path-resource existence** — every path-templated resource
        exists, validated strictly left to right. Applies to every endpoint with a path
        parameter. Rejection is the 404 code matching the first path segment that fails
        to resolve: `ERR_RESTAURANT_NOT_FOUND`, `ERR_PROFILE_NOT_FOUND`,
        `ERR_STAFF_NOT_FOUND`, `ERR_DEPLOYMENT_NOT_FOUND`, `ERR_LOOP_NOT_FOUND`,
        `ERR_SLOT_NOT_FOUND`, `ERR_PULL_FORWARD_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`,
        `ERR_REPORT_NOT_FOUND`, `ERR_COACHING_NOT_FOUND` or `ERR_OVERRIDE_NOT_FOUND`
        (all 404)."

        Design: Corner/errors/err_absent_child_identifier_returns_typed_not_found
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-50",
            staff_name="Corner Alba",
            name="Corner Typed Not Found Store",
        )
        absent = ABSENT_UUID

        observed = [
            validate_error(
                api.greet_timer_loop(absent, ctx.leader_headers), ERR_LOOP_NOT_FOUND
            )["error_id"],
            validate_error(
                api.commit_merge_slot(absent, ctx.leader_headers), ERR_SLOT_NOT_FOUND
            )["error_id"],
            validate_error(
                api.park_pull_forward_order(absent, ctx.leader_headers),
                ERR_PULL_FORWARD_NOT_FOUND,
            )["error_id"],
            validate_error(
                api.close_accuracy_incident(absent, AUDITOR_HEADERS),
                ERR_INCIDENT_NOT_FOUND,
            )["error_id"],
            validate_error(
                api.publish_throughput_report(absent, COACH_HEADERS),
                ERR_REPORT_NOT_FOUND,
            )["error_id"],
            validate_error(
                api.issue_coaching_intervention(absent, COACH_HEADERS),
                ERR_COACHING_NOT_FOUND,
            )["error_id"],
            validate_error(
                api.approve_forecast_override(absent, ADMIN_HEADERS),
                ERR_OVERRIDE_NOT_FOUND,
            )["error_id"],
            validate_error(
                api.activate_deployment(absent, ctx.operator_headers),
                ERR_DEPLOYMENT_NOT_FOUND,
            )["error_id"],
        ]
        a.assert_distinct(observed)

        for lister in (api.list_timer_loops, api.list_merge_slots):
            _rows, meta = validate_paginated(
                lister(ADMIN_HEADERS, {"restaurant_id": ctx.restaurant_id})
            )
            assert meta["total_count"] == 0, meta


class TestAuthenticationPrecedesEverything:
    """Rung one of the ladder: who are you."""

    def test_a_role_without_an_identity_and_an_undeclared_role_are_both_401(
        self, api: DriveThruApiClient
    ):
        """PRD §2.11: "**Authentication** — both headers present and `X-User-Role` among
        the five declared roles. Applies to every endpoint. Rejection:
        `ERR_UNAUTHENTICATED` (401)."
        And: "The first violated rule in this list wins, and its error is the one
        returned."

        Design: Corner/errors/err_missing_user_id_header_rejected
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-51",
            staff_name="Corner Dov",
            name="Corner Authentication Store",
        )
        body = f.timer_loop_body(ctx.restaurant_id, ctx.profile_id)

        # ShiftLeader is on this endpoint's role list, so only the missing identity
        # can be at fault.
        anonymous = validate_error_is_one_of(
            api.create_timer_loop(body, headers_without_user_id(ROLE_SHIFT_LEADER)),
            [ERR_UNAUTHENTICATED, ERR_STAFF_SCOPE_MISMATCH, ERR_UNAUTHORIZED],
        )
        assert anonymous == ERR_UNAUTHENTICATED

        undeclared = validate_error_is_one_of(
            api.create_timer_loop(
                body, build_user_headers(ctx.staff_id, UNKNOWN_ROLE)
            ),
            [ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED],
        )
        assert undeclared == ERR_UNAUTHENTICATED

        _rows, meta = validate_paginated(
            api.list_timer_loops(ADMIN_HEADERS, {"restaurant_id": ctx.restaurant_id})
        )
        assert meta["total_count"] == 0, meta


class TestPublishIsNotIdempotent:
    """The second publish is a state error, not a repeat success."""

    def test_republishing_a_published_report_is_refused(self, api: DriveThruApiClient):
        """PRD §3.8: "Publishing moves the report `DRAFT → PUBLISHED` and requires the
        report to be in `DRAFT`, `cars_served` to be at least 1, and the store not to be
        frozen."
        PRD §2.11: "**Declared transition** — the target resource is in a state from
        which the requested transition is declared. Applies to every action endpoint.
        Rejection is the code matching the resource: `ERR_INVALID_PROFILE_STATE`,
        `ERR_INVALID_DEPLOYMENT_STATE`, `ERR_INVALID_TIMER_STATE`,
        `ERR_INVALID_SLOT_STATE`, `ERR_INVALID_PULL_FORWARD_STATE`,
        `ERR_INVALID_INCIDENT_STATE`, `ERR_INVALID_REPORT_STATE`,
        `ERR_INVALID_COACHING_STATE` or `ERR_INVALID_OVERRIDE_STATE` (all 409)."

        Design: Corner/errors/err_publish_published_report_returns_invalid_report_state
        """
        fx.setup_four_tier_bands(api)
        ctx = fx.setup_store(
            api,
            "C-2398-52",
            staff_name="Corner Ken",
            name="Corner Republish Store",
        )
        fx.drive_loop(
            api,
            ctx,
            arrive_at=fx.at(11, 0, 0),
            greet_at=fx.at(11, 0, 20),
            order_complete_at=fx.at(11, 1, 0),
            window_arrive_at=fx.at(11, 2, 0),
            depart_at=fx.at(11, 4, 10),
            order_items_count=3,
        )
        fx.set_clock(api, fx.at(11, 5, 0))
        report = fx.create_published_report(api, ctx, fx.at(11, 0, 0), fx.at(11, 5, 0))
        a.assert_report_metrics(report, cars_served=1)
        assert report["report_state"] == "PUBLISHED", report

        # A non-empty window, so the empty-window gate is not the one in play.
        error_id = validate_error_is_one_of(
            api.publish_throughput_report(report["id"], COACH_HEADERS),
            [ERR_INVALID_REPORT_STATE, ERR_REPORT_WINDOW_EMPTY, ERR_REPORT_NOT_FOUND],
        )
        assert error_id == ERR_INVALID_REPORT_STATE

        stored = validate_success(
            api.get_throughput_report(report["id"], ADMIN_HEADERS)
        )
        assert stored["report_state"] == "PUBLISHED", stored
        rows, meta = validate_paginated(
            api.list_throughput_reports(
                ADMIN_HEADERS,
                {"restaurant_id": ctx.restaurant_id, "report_state": "PUBLISHED"},
            )
        )
        assert meta["total_count"] == 1, meta
        assert rows[0]["id"] == report["id"], rows


class TestOverrideApplyNeedsApproval:
    """The approval rung cannot be skipped."""

    def test_applying_a_proposed_override_is_refused_and_moves_no_car_rate(
        self, api: DriveThruApiClient
    ):
        """PRD §3.7: "It requires the override to be in `APPROVED`, the store not to be
        frozen, and it enforces an **aggregate capacity cap** across the store's
        already-applied overrides: take every override of this store whose `fo_state` is
        `APPLIED` and whose closed interval intersects this one — touching endpoints
        count as intersecting — sum the absolute values of their
        `projected_cars_delta_pct`, add the absolute value of this override's own
        `projected_cars_delta_pct`, and the total must not exceed 0.50."
        And: "A proposed override starts at `fo_state` `PROPOSED`, with
        `approved_by_user_id` and `rejection_reason` null, and it has **no effect
        whatsoever** on any store rollup — proposing changes no target and no tier."

        Design: Corner/errors/err_apply_before_approve_returns_invalid_override_state
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-53",
            staffing_basis="FORECAST_ADJUSTED",
            with_staff=False,
            with_active_lunch_profile=False,
            name="Corner Apply Order Store",
        )
        override = fx.propose_override(
            api,
            ctx,
            fx.at(11, 0, 0),
            fx.at(12, 0, 0),
            projected_cars_delta_pct=0.25,
            source="WEATHER",
        )
        assert override["fo_state"] == "PROPOSED", override

        # 0.25 is well inside the aggregate cap, so only the state gate can fail.
        error_id = validate_error_is_one_of(
            api.apply_forecast_override(override["id"], ctx.operator_headers),
            [ERR_INVALID_OVERRIDE_STATE, ERR_OVERRIDE_AGGREGATE_CAP],
        )
        assert error_id == ERR_INVALID_OVERRIDE_STATE

        stored = validate_success(
            api.get_forecast_override(override["id"], ADMIN_HEADERS)
        )
        assert stored["fo_state"] == "PROPOSED", stored
        assert stored["approved_by_user_id"] is None, stored
        a.assert_rollup(
            fx.get_restaurant(api, ctx.restaurant_id),
            cars_per_hour_effective=0.0,
            volume_tier="TIER_1",
        )


class TestClearedPullForwardIsTerminal:
    """A cleared order stays cleared."""

    def test_a_second_clear_neither_succeeds_nor_re_stamps_the_first(
        self, api: DriveThruApiClient
    ):
        """PRD §3.7: "Clearing moves the order to `CLEARED` and is reachable from both
        `ISSUED` and `PARKED`, in each case requiring an unfrozen store."
        And: "`CLEARED` and `CANCELLED` are both terminal."

        Design: Corner/errors/err_clear_cleared_pull_forward_returns_invalid_state
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-54",
            staff_name="Corner Rhea",
            name="Corner Clear Twice Store",
        )
        loop = fx.drive_loop(
            api,
            ctx,
            arrive_at=fx.at(11, 0, 0),
            greet_at=fx.at(11, 0, 20),
            order_complete_at=fx.at(11, 1, 0),
            window_arrive_at=None,
        )
        order = fx.issue_pull_forward(api, ctx, loop["id"], reason="ITEM_LAG")
        assert order["pf_state"] == "ISSUED", order
        assert order["escalation_count"] == 0, order

        fx.set_clock(api, fx.at(11, 1, 30))
        cleared = validate_success(
            api.clear_pull_forward_order(order["id"], ctx.leader_headers)
        )
        assert cleared["pf_state"] == "CLEARED", cleared
        assert cleared["cleared_at"] == fx.at(11, 1, 30), cleared

        fx.set_clock(api, fx.at(11, 2, 0))
        validate_error(
            api.clear_pull_forward_order(order["id"], ctx.leader_headers),
            ERR_INVALID_PULL_FORWARD_STATE,
        )

        stored = validate_success(
            api.get_pull_forward_order(order["id"], ADMIN_HEADERS)
        )
        assert stored["cleared_at"] == fx.at(11, 1, 30), stored
        assert stored["escalation_count"] == 0, stored
        untouched = validate_success(api.get_timer_loop(loop["id"], ADMIN_HEADERS))
        a.assert_loop_states(untouched, timing_state="ORDERED")
        a.assert_loop_segments(untouched, adjusted_total_seconds=None)


class TestAcknowledgeNeedsAnIssuedIntervention:
    """The coachee is the right actor at the wrong time."""

    def test_the_named_coachee_still_cannot_acknowledge_a_draft(
        self, api: DriveThruApiClient
    ):
        """PRD §3.9: "Acknowledging moves the intervention `ISSUED → ACKNOWLEDGED` and
        requires it to be in `ISSUED`, the acting `X-User-ID` to equal the
        intervention's `staff_member_id`, and the store not to be frozen."

        Design: Corner/errors/err_acknowledge_draft_coaching_returns_invalid_coaching_state
        """
        fx.setup_four_tier_bands(api)
        ctx = fx.setup_store(
            api,
            "C-2398-55",
            staff_name="Corner Ada",
            name="Corner Draft Acknowledge Store",
        )
        fx.drive_loop(
            api,
            ctx,
            arrive_at=fx.at(11, 0, 0),
            greet_at=fx.at(11, 0, 20),
            order_complete_at=fx.at(11, 1, 0),
            window_arrive_at=fx.at(11, 2, 0),
            depart_at=fx.at(11, 4, 10),
            order_items_count=3,
        )
        fx.set_clock(api, fx.at(11, 5, 0))
        report = fx.create_published_report(api, ctx, fx.at(11, 0, 0), fx.at(11, 5, 0))
        coaching = fx.create_coaching(api, report["id"], ctx.staff_id, "ORDER")
        assert coaching["ci_state"] == "DRAFT", coaching
        assert coaching["issued_by_user_id"] is None, coaching
        # An order taken in 40 seconds beat its 95-second target, so no gap.
        a.assert_coaching_scoring(coaching, segment_gap_seconds=0)

        error_id = validate_error_is_one_of(
            api.acknowledge_coaching_intervention(coaching["id"], ctx.leader_headers),
            [ERR_INVALID_COACHING_STATE, ERR_STAFF_SCOPE_MISMATCH],
        )
        assert error_id == ERR_INVALID_COACHING_STATE

        stored = validate_success(
            api.get_coaching_intervention(coaching["id"], ADMIN_HEADERS)
        )
        assert stored["ci_state"] == "DRAFT", stored
        assert stored["revision_count"] == 0, stored


class TestForfeitedSlotCannotBeCommitted:
    """The slot state gate fires before the cross-entity gate."""

    def test_a_slot_a_pull_forward_forfeited_is_no_longer_committable(
        self, api: DriveThruApiClient
    ):
        """PRD §3.7: "Issuing also has an immediate structural consequence — any merge
        slot the loop holds in `RESERVED` becomes `FORFEITED` and `merge_slots_free` is
        recomputed upward by one."
        PRD §2.11: "**Cross-entity state gates** — timer-loop creation needs the
        referenced profile in `ACTIVE` (`ERR_PROFILE_NOT_ACTIVE`); coaching creation
        needs the referenced report in `PUBLISHED` (`ERR_REPORT_NOT_PUBLISHED`);
        deployment activation needs the team member in `AVAILABLE`
        (`ERR_STAFF_NOT_AVAILABLE`); a merge commit needs the awarded loop in `ORDERED`
        (`ERR_LOOP_NOT_MERGEABLE`); logging an accuracy incident needs the loop's
        `timing_state` to be one of `ORDERED`, `MERGED`, `AT_WINDOW` or `CLOSED`
        (`ERR_LOOP_HAS_NO_ORDER`); and a loop may carry only one non-terminal remake
        (`ERR_REMAKE_ALREADY_OPEN`)."

        Design: Corner/errors/err_commit_forfeited_slot_returns_invalid_slot_state
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-56",
            lane_config="DUAL_PARALLEL",
            merge_slots_capacity=2,
            staff_name="Corner Yusuf",
            name="Corner Forfeited Slot Store",
        )
        loop = fx.drive_loop(
            api,
            ctx,
            lane="LANE_A",
            arrive_at=fx.at(11, 0, 0),
            greet_at=fx.at(11, 0, 20),
            order_complete_at=fx.at(11, 1, 0),
            window_arrive_at=None,
        )
        slot = fx.award_merge_slot(api, ctx)
        assert slot["slot_state"] == "RESERVED", slot
        fx.issue_pull_forward(api, ctx, loop["id"], reason="ITEM_LAG")
        forfeited = validate_success(api.get_merge_slot(slot["id"], ADMIN_HEADERS))
        assert forfeited["slot_state"] == "FORFEITED", forfeited

        # The awarded loop is still ORDERED, so the cross-entity gate would pass.
        error_id = validate_error_is_one_of(
            api.commit_merge_slot(slot["id"], ctx.leader_headers),
            [ERR_INVALID_SLOT_STATE, ERR_LOOP_NOT_MERGEABLE],
        )
        assert error_id == ERR_INVALID_SLOT_STATE

        stored_loop = validate_success(api.get_timer_loop(loop["id"], ADMIN_HEADERS))
        a.assert_loop_states(stored_loop, timing_state="ORDERED")
        assert stored_loop["merge_at"] is None, stored_loop
        a.assert_loop_segments(stored_loop, merge_wait_seconds=None)
        a.assert_merge_capacity(fx.get_restaurant(api, ctx.restaurant_id), free=2)


class TestActivationNeedsAnAvailableMember:
    """One body, one post."""

    def test_a_deployed_member_cannot_be_activated_onto_a_second_post(
        self, api: DriveThruApiClient
    ):
        """PRD §3.4: "Activation — moving `PLANNED → ACTIVE`, available to both an
        `Operator` and a `ShiftLeader` — requires the deployment to be in `PLANNED`, the
        store not to be frozen, the member's `staff_state` to be `AVAILABLE`, and the
        store's `labor_minutes_available` to be at least this deployment's
        `planned_minutes`; a shortfall is `ERR_LABOR_BUDGET_EXCEEDED` (402)."
        And: "For every *other* deployment of the same member whose `deployment_state`
        is `PLANNED` or `ACTIVE`, the new deployment must satisfy one of two conditions —
        either its `planned_start_at` is at or after that other deployment's
        `planned_end_at` plus 600 seconds, or its `planned_end_at` plus 600 seconds is at
        or before that other deployment's `planned_start_at`."

        Design: Corner/errors/err_activate_for_deployed_member_returns_staff_not_available
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-57",
            labor_minutes_budget=600,
            staff_name="Corner Nils",
            name="Corner Double Post Store",
        )
        fx.set_clock(api, fx.at(11, 0, 0))
        first = fx.plan_deployment(api, ctx, fx.at(11, 0, 0), fx.at(12, 0, 0))
        activated = fx.activate_deployment(api, ctx, first["id"])
        assert activated["deployment_state"] == "ACTIVE", activated
        # An hour clear of the first block, so the changeover buffer is satisfied.
        second = fx.plan_deployment(api, ctx, fx.at(13, 0, 0), fx.at(14, 0, 0))
        a.assert_deployment_charge(second, planned_minutes=60)
        assert second["deployment_state"] == "PLANNED", second

        member = validate_success(api.get_staff_member(ctx.staff_id, ADMIN_HEADERS))
        assert member["staff_state"] == "DEPLOYED", member
        store_before = fx.get_restaurant(api, ctx.restaurant_id)
        # 540 available against 60 planned, so the budget gate cannot be the one.
        a.assert_labor_ledger(store_before, committed=60, available=540)

        error_id = validate_error_is_one_of(
            api.activate_deployment(second["id"], ctx.operator_headers),
            [
                ERR_STAFF_NOT_AVAILABLE,
                ERR_LABOR_BUDGET_EXCEEDED,
                ERR_DEPLOYMENT_BUFFER_VIOLATION,
            ],
        )
        assert error_id == ERR_STAFF_NOT_AVAILABLE

        stored = validate_success(api.get_deployment(second["id"], ADMIN_HEADERS))
        assert stored["deployment_state"] == "PLANNED", stored
        assert stored["activated_at"] is None, stored
        a.assert_deployment_charge(stored, labor_minutes_charged=0)
        store_after = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_labor_ledger(store_after, committed=60)
        a.assert_rollup(store_after, deployed_oot_count=1)


class TestActivationNeedsLaborBudget:
    """The budget shortfall is its own payment-required refusal."""

    def test_a_second_block_beyond_the_budget_leaves_the_ledger_where_it_was(
        self, api: DriveThruApiClient
    ):
        """PRD §3.4: "Activation — moving `PLANNED → ACTIVE`, available to both an
        `Operator` and a `ShiftLeader` — requires the deployment to be in `PLANNED`, the
        store not to be frozen, the member's `staff_state` to be `AVAILABLE`, and the
        store's `labor_minutes_available` to be at least this deployment's
        `planned_minutes`; a shortfall is `ERR_LABOR_BUDGET_EXCEEDED` (402)."
        And: "Across all four states the invariant that must hold after every request is
        that `labor_minutes_budget` equals `labor_minutes_committed` plus
        `labor_minutes_available`; deployments in `PLANNED` and `ABORTED` contribute zero
        to the committed side."

        Design: Corner/errors/err_activate_beyond_available_labor_returns_budget_exceeded
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-58",
            labor_minutes_budget=100,
            staff_name="Corner Freya",
            name="Corner Budget Ceiling Store",
        )
        second_member = fx.add_staff_member(
            api,
            ctx.restaurant_id,
            "Corner Onyx",
            oot_certified=True,
            window_certified=True,
        )
        a.assert_labor_ledger(
            fx.get_restaurant(api, ctx.restaurant_id), available=100
        )
        fx.set_clock(api, fx.at(11, 0, 0))

        first = fx.plan_deployment(api, ctx, fx.at(11, 0, 0), fx.at(12, 0, 0))
        fx.activate_deployment(api, ctx, first["id"])
        a.assert_labor_ledger(
            fx.get_restaurant(api, ctx.restaurant_id), committed=60, available=40
        )

        second = fx.plan_deployment(
            api,
            ctx,
            fx.at(13, 0, 0),
            fx.at(14, 0, 0),
            staff_member_id=second_member["id"],
            position="OOT_LANE_B",
        )
        a.assert_deployment_charge(second, planned_minutes=60)
        assert second_member["staff_state"] == "AVAILABLE", second_member

        error_id = validate_error_is_one_of(
            api.activate_deployment(second["id"], ctx.leader_headers),
            [
                ERR_LABOR_BUDGET_EXCEEDED,
                ERR_STAFF_NOT_AVAILABLE,
                ERR_STAFF_NOT_OOT_CERTIFIED,
            ],
        )
        assert error_id == ERR_LABOR_BUDGET_EXCEEDED

        stored = validate_success(api.get_deployment(second["id"], ADMIN_HEADERS))
        assert stored["deployment_state"] == "PLANNED", stored
        bench = validate_success(
            api.get_staff_member(second_member["id"], ADMIN_HEADERS)
        )
        assert bench["staff_state"] == "AVAILABLE", bench
        a.assert_labor_ledger(
            fx.get_restaurant(api, ctx.restaurant_id), committed=60, available=40
        )


class TestBodyForeignKeyExistence:
    """A body key that resolves to nothing is a 404, not a state error."""

    def test_a_loop_naming_an_absent_profile_is_a_profile_not_found(
        self, api: DriveThruApiClient
    ):
        """PRD §2.11: "**Body foreign-key existence** — every foreign key named in the
        body resolves to a row."
        And: "**Same-store referential integrity** — every body foreign key belongs to
        the same store as the operation's target."

        Design: Corner/errors/err_absent_body_profile_fk_returns_profile_not_found
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-59",
            with_active_lunch_profile=False,
            staff_name="Corner Bruno",
            name="Corner Absent Profile Store",
        )
        fx.set_clock(api, fx.at(11, 0, 0))

        # Neither the active-profile gate nor the same-store gate can be evaluated
        # against a row that does not exist.
        error_id = validate_error_is_one_of(
            api.create_timer_loop(
                f.timer_loop_body(ctx.restaurant_id, ABSENT_UUID),
                ctx.leader_headers,
            ),
            [
                ERR_PROFILE_NOT_FOUND,
                ERR_PROFILE_NOT_ACTIVE,
                ERR_RESTAURANT_MISMATCH,
                ERR_RESTAURANT_NOT_FOUND,
            ],
        )
        assert error_id == ERR_PROFILE_NOT_FOUND

        _rows, meta = validate_paginated(
            api.list_timer_loops(ADMIN_HEADERS, {"restaurant_id": ctx.restaurant_id})
        )
        assert meta["total_count"] == 0, meta
