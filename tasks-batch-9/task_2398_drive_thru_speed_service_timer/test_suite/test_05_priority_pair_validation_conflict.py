"""Requests that break two rules at once, to pin the priority ladder.

Each scenario is built so that two guards are genuinely violated by the same
call, and only the higher-priority guard's error may come back.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.api_client import DriveThruApiClient
from test_helpers.api_errors import (
    ERR_DEPLOYMENT_BUFFER_VIOLATION,
    ERR_INVALID_DEPLOYMENT_STATE,
    ERR_LABOR_BUDGET_EXCEEDED,
    ERR_PROFILE_NOT_ACTIVE,
    ERR_PROFILE_NOT_FOUND,
    ERR_RESTAURANT_MISMATCH,
    ERR_STAFF_NOT_AVAILABLE,
    ERR_STAFF_NOT_OOT_CERTIFIED,
)
from test_helpers.test_users import ADMIN_HEADERS


# ------------------------------------- declared transition over the labor budget
def _store_whose_whole_budget_is_already_on_position(api: DriveThruApiClient):
    """A store with a 30-minute budget spent by one active deployment."""
    fx.setup_four_tier_bands(api)
    ctx = fx.setup_store(
        api,
        "S-2398-J",
        labor_minutes_budget=30,
        staff_name="Ivy Marsh",
        name="Marietta Tight Budget",
    )
    fx.set_clock(api, fx.at(11, 0, 0))
    deployment = fx.plan_deployment(api, ctx, fx.at(11, 0, 0), fx.at(11, 30, 0))
    fx.activate_deployment(api, ctx, deployment["id"])
    return ctx, deployment["id"]


class TestStateOverFiscalOnActivate:
    """Re-activating an active deployment breaks three guards at once."""

    def test_second_activation_returns_the_state_error(self, api):
        """PRD §2.11: "a request that would both exceed the labor budget and be
        in the wrong state returns the state error."

        Design: Difficulty/priority_pair_validation_conflict/state_over_fiscal_on_deployment_activate
        """
        ctx, deployment_id = _store_whose_whole_budget_is_already_on_position(api)

        validate_error(
            api.activate_deployment(deployment_id, ctx.operator_headers),
            ERR_INVALID_DEPLOYMENT_STATE,
        )

    def test_neither_the_availability_gate_nor_the_budget_gate_may_answer(self, api):
        """PRD §2.11: "**Declared transition** — the target resource is in a state
        from which the requested transition is declared."

        Design: Difficulty/priority_pair_validation_conflict/state_over_fiscal_on_deployment_activate
        """
        ctx, deployment_id = _store_whose_whole_budget_is_already_on_position(api)

        # The member is DEPLOYED and the budget is spent, so all three guards fail.
        staff = validate_success(api.get_staff_member(ctx.staff_id, ADMIN_HEADERS))
        assert staff["staff_state"] == "DEPLOYED", staff
        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_labor_ledger(store, committed=30, available=0)

        error_id = validate_error_is_one_of(
            api.activate_deployment(deployment_id, ctx.operator_headers),
            [
                ERR_INVALID_DEPLOYMENT_STATE,
                ERR_STAFF_NOT_AVAILABLE,
                ERR_LABOR_BUDGET_EXCEEDED,
            ],
        )
        assert error_id == ERR_INVALID_DEPLOYMENT_STATE, error_id

    def test_the_rejected_retry_charges_nothing_twice(self, api):
        """PRD §3.2: "On success `activated_at` is stamped from the logical clock,
        the member moves to `DEPLOYED`, the deployment's full `planned_minutes`
        join `labor_minutes_committed`, `labor_minutes_available` is re-derived,
        and the rollup chain runs"

        Design: Difficulty/priority_pair_validation_conflict/state_over_fiscal_on_deployment_activate
        """
        ctx, deployment_id = _store_whose_whole_budget_is_already_on_position(api)

        validate_error(
            api.activate_deployment(deployment_id, ctx.operator_headers),
            ERR_INVALID_DEPLOYMENT_STATE,
        )

        deployment = validate_success(
            api.get_deployment(deployment_id, ADMIN_HEADERS)
        )
        assert deployment["deployment_state"] == "ACTIVE", deployment
        # PRD §3.2: activation moves `planned_minutes` into
        # `labor_minutes_committed` but does NOT touch `labor_minutes_charged`,
        # which a freshly planned deployment starts at 0 and only *release*
        # writes ("sets `labor_minutes_charged` to the lesser of
        # `planned_minutes` and the elapsed activation time"). A deployment that
        # is still ACTIVE has therefore been charged nothing.
        a.assert_deployment_charge(
            deployment, planned_minutes=30, labor_minutes_charged=0
        )
        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_labor_ledger(store, committed=30, available=0)


# ------------------------------------- certification over the changeover buffer
def _store_with_an_uncertified_member_already_on_the_expediter_slot(
    api: DriveThruApiClient,
):
    """A member who cannot take an outside order-taker position, already booked."""
    fx.setup_four_tier_bands(api)
    ctx = fx.setup_store(
        api,
        "S-2398-K",
        staff_name="Rory Vance",
        oot_certified=False,
        name="Alpharetta Expediter Store",
    )
    fx.set_clock(api, fx.at(11, 0, 0))
    first = fx.plan_deployment(
        api, ctx, fx.at(11, 0, 0), fx.at(11, 30, 0), position="EXPEDITER"
    )
    return ctx, first["id"]


class TestSafetyOverTemporalOnDeploymentCreate:
    """An uncertified back-to-back plan reports the certification failure."""

    def test_certification_answers_before_the_buffer_geometry(self, api):
        """PRD §2.11: "**Outside-order-taker certification** — a deployment at
        `OOT_LANE_A` or `OOT_LANE_B` requires the team member's `oot_certified`
        to be true."

        Design: Difficulty/priority_pair_validation_conflict/safety_over_temporal_on_deployment_create
        """
        ctx, _first_id = _store_with_an_uncertified_member_already_on_the_expediter_slot(
            api
        )

        error_id = validate_error_is_one_of(
            api.create_deployment(
                {
                    "restaurant_id": ctx.restaurant_id,
                    "staff_member_id": ctx.staff_id,
                    "daypart_profile_id": ctx.profile_id,
                    "position": "OOT_LANE_A",
                    "planned_start_at": fx.at(11, 30, 0),
                    "planned_end_at": fx.at(12, 0, 0),
                },
                ctx.operator_headers,
            ),
            [ERR_STAFF_NOT_OOT_CERTIFIED, ERR_DEPLOYMENT_BUFFER_VIOLATION],
        )
        assert error_id == ERR_STAFF_NOT_OOT_CERTIFIED, error_id

    def test_the_rejection_is_the_certification_status_code(self, api):
        """PRD §3.2: "First, a deployment at `OOT_LANE_A` or `OOT_LANE_B` requires
        the named member's `oot_certified` to be true; otherwise the plan is
        rejected with `ERR_STAFF_NOT_OOT_CERTIFIED`."

        Design: Difficulty/priority_pair_validation_conflict/safety_over_temporal_on_deployment_create
        """
        ctx, _first_id = _store_with_an_uncertified_member_already_on_the_expediter_slot(
            api
        )

        staff = validate_success(api.get_staff_member(ctx.staff_id, ADMIN_HEADERS))
        assert staff["oot_certified"] is False, staff

        validate_error(
            api.create_deployment(
                {
                    "restaurant_id": ctx.restaurant_id,
                    "staff_member_id": ctx.staff_id,
                    "daypart_profile_id": ctx.profile_id,
                    "position": "OOT_LANE_A",
                    "planned_start_at": fx.at(11, 30, 0),
                    "planned_end_at": fx.at(12, 0, 0),
                },
                ctx.operator_headers,
            ),
            ERR_STAFF_NOT_OOT_CERTIFIED,
        )

    def test_the_rejected_plan_is_not_persisted(self, api):
        """PRD §3.2: "A freshly planned deployment has `deployment_state` of
        `PLANNED`, its `activated_at` and `released_at` are null, its
        `labor_minutes_charged` is 0, and — importantly — no labor has been
        committed against the store yet."

        Design: Difficulty/priority_pair_validation_conflict/safety_over_temporal_on_deployment_create
        """
        ctx, first_id = _store_with_an_uncertified_member_already_on_the_expediter_slot(
            api
        )

        validate_error(
            api.create_deployment(
                {
                    "restaurant_id": ctx.restaurant_id,
                    "staff_member_id": ctx.staff_id,
                    "daypart_profile_id": ctx.profile_id,
                    "position": "OOT_LANE_A",
                    "planned_start_at": fx.at(11, 30, 0),
                    "planned_end_at": fx.at(12, 0, 0),
                },
                ctx.operator_headers,
            ),
            ERR_STAFF_NOT_OOT_CERTIFIED,
        )

        rows, meta = validate_paginated(
            api.list_deployments(
                ADMIN_HEADERS, {"restaurant_id": ctx.restaurant_id}
            )
        )
        assert meta["total_count"] == 1, meta
        assert rows[0]["id"] == first_id, rows
        assert rows[0]["deployment_state"] == "PLANNED", rows[0]
        a.assert_deployment_charge(
            rows[0], planned_minutes=30, labor_minutes_charged=0
        )
        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_labor_ledger(store, committed=0, available=300)


# ------------------------------- same-store ownership over the profile's state
def _two_stores_one_active_profile_and_one_draft_profile(api: DriveThruApiClient):
    """Store A with an ACTIVE lunch profile, store B with a DRAFT one."""
    fx.setup_four_tier_bands(api)
    store_a = fx.setup_store(
        api,
        "S-2398-L",
        staff_name="Dana Whitlock",
        name="Store A Peachtree",
    )
    store_b = fx.setup_store(
        api,
        "S-2398-M",
        with_staff=False,
        with_active_lunch_profile=False,
        name="Store B Ponce",
    )
    foreign_profile = fx.create_daypart_profile(api, store_b.restaurant_id)
    fx.set_clock(api, fx.at(11, 0, 0))
    return store_a, store_b, foreign_profile["id"]


class TestReferentialOverStateOnTimerLoopCreate:
    """Naming another store's draft profile is a mismatch, not a state problem."""

    def test_cross_store_profile_reference_is_a_mismatch(self, api):
        """PRD §2.11: "**Same-store referential integrity** — every body foreign
        key belongs to the same store as the operation's target."

        Design: Difficulty/priority_pair_validation_conflict/referential_over_state_on_timer_loop_create
        """
        store_a, _store_b, foreign_profile_id = (
            _two_stores_one_active_profile_and_one_draft_profile(api)
        )

        error_id = validate_error_is_one_of(
            api.create_timer_loop(
                {
                    "restaurant_id": store_a.restaurant_id,
                    "daypart_profile_id": foreign_profile_id,
                    "lane": "SINGLE",
                },
                store_a.leader_headers,
            ),
            [ERR_RESTAURANT_MISMATCH, ERR_PROFILE_NOT_ACTIVE, ERR_PROFILE_NOT_FOUND],
        )
        assert error_id == ERR_RESTAURANT_MISMATCH, error_id

    def test_ownership_outranks_business_rules_and_the_row_does_exist(self, api):
        """PRD §2.12: "Body-level identifiers are resolved after the whole path
        resolves, and a body identifier that resolves to a row belonging to a
        *different* store than the operation's target is a conflict rather than a
        not-found: it is rejected with `ERR_RESTAURANT_MISMATCH` (409). Existence
        therefore always precedes ownership, and ownership always precedes
        business rules."

        Design: Difficulty/priority_pair_validation_conflict/referential_over_state_on_timer_loop_create
        """
        store_a, store_b, foreign_profile_id = (
            _two_stores_one_active_profile_and_one_draft_profile(api)
        )

        foreign = validate_success(
            api.get_daypart_profile(foreign_profile_id, ADMIN_HEADERS)
        )
        assert foreign["profile_state"] == "DRAFT", foreign
        assert foreign["restaurant_id"] == store_b.restaurant_id, foreign

        validate_error(
            api.create_timer_loop(
                {
                    "restaurant_id": store_a.restaurant_id,
                    "daypart_profile_id": foreign_profile_id,
                    "lane": "SINGLE",
                },
                store_a.leader_headers,
            ),
            ERR_RESTAURANT_MISMATCH,
        )

    def test_no_loop_is_opened_at_either_store(self, api):
        """PRD §3.3: "A `ShiftLeader` opens a loop when a car breaks the lane
        sensor, supplying the `restaurant_id`, the `daypart_profile_id` whose
        targets should govern this car, and the `lane`."

        Design: Difficulty/priority_pair_validation_conflict/referential_over_state_on_timer_loop_create
        """
        store_a, store_b, foreign_profile_id = (
            _two_stores_one_active_profile_and_one_draft_profile(api)
        )

        validate_error(
            api.create_timer_loop(
                {
                    "restaurant_id": store_a.restaurant_id,
                    "daypart_profile_id": foreign_profile_id,
                    "lane": "SINGLE",
                },
                store_a.leader_headers,
            ),
            ERR_RESTAURANT_MISMATCH,
        )

        for restaurant_id in (store_a.restaurant_id, store_b.restaurant_id):
            _rows, meta = validate_paginated(
                api.list_timer_loops(ADMIN_HEADERS, {"restaurant_id": restaurant_id})
            )
            assert meta["total_count"] == 0, (restaurant_id, meta)

        foreign = validate_success(
            api.get_daypart_profile(foreign_profile_id, ADMIN_HEADERS)
        )
        assert foreign["profile_state"] == "DRAFT", foreign
