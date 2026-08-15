"""The drill-and-blast program: shot plan lifecycle, firing gates, muckpile."""
import pytest

from test_helpers import (
    FOREMAN,
    MANAGER,
    SALES,
    ApiErrorId,
    advance_plan_to_loaded,
    create_approved_plan,
    create_bench,
    create_order,
    create_released_bench,
    create_shot_plan,
    create_site,
    create_spec,
    create_training,
    create_zone,
    get_shot_plan,
    get_site,
    make_site_manager_headers,
    post_bond,
    queue_truck,
    set_clock,
    setup_blast_site,
    submit_plan,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestInitialStates:
    def test_entities_initial_states_on_create(self, api):
        """PRD 3.2: "A bench is born `PLANNED` and counts against nothing."
        PRD 3.3: "The plan is born in `DRAFT` with `drilled_hole_count` at
        zero and `loaded_explosive_lbs` unset."
        PRD 3.6: "The order is born `QUOTED` with `fulfilled_tons` at zero,
        `prices_pinned` false, and `stockpile_id` unset".
        PRD 3.7: "The entry is born `QUEUED` with `queued_at` stamped from
        the logical clock and `scale_ticket_id` unset."

        Design: Corner/state_machines/entities_initial_states_on_create
        """
        site = create_site()
        spec = create_spec()
        zone = create_zone()
        bench = create_bench(site["id"])
        assert bench["status"] == "PLANNED"
        plan = create_shot_plan(bench["id"])
        assert plan["status"] == "DRAFT"
        assert plan["drilled_hole_count"] == 0
        assert plan.get("loaded_explosive_lbs") is None
        order = create_order(site["id"], spec["id"], zone["id"],
                             quantity_tons=30)
        assert order["status"] == "QUOTED"
        assert order["prices_pinned"] is False
        assert order["fulfilled_tons"] == pytest.approx(0, abs=1e-9)
        assert order.get("stockpile_id") is None
        entry = queue_truck(site["id"], truck_id="TRK-1")
        assert entry["status"] == "QUEUED"
        assert entry.get("scale_ticket_id") is None


class TestShotPlanStateMachine:
    def test_shotplan_fire_from_draft_rejected(self, api):
        """PRD 2.7 tier 5: "Own state — the target resource's own state must
        permit the requested transition, and terminal states accept no
        further transitions at all, otherwise `ERR_INVALID_STATE` (409)."
        PRD 3.3 defines firing as the `LOADED` → `FIRED` transition.

        Design: Corner/state_machines/shotplan_fire_from_draft_rejected
        """
        site = create_site()
        bench = create_bench(site["id"])
        plan = create_shot_plan(bench["id"])
        resp = api.fire_shot_plan(plan["id"], FOREMAN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_shot_plan(plan["id"])["status"] == "DRAFT"
        data, _meta = validate_paginated(
            api.list_muckpiles(MANAGER, params={"shot_plan_id": plan["id"]}))
        assert data == []

    def test_shotplan_drill_redrill_cycle_resets_count(self, api):
        """PRD 3.3: "Collapsed or flooded holes reopen the loop: a redrill
        returns the plan `DRILLED` → `DRILLING`, requires a `RELEASED` bench
        and a non-`SUSPENDED` posture, and resets `drilled_hole_count` to
        zero."

        Design: Difficulty/non_linear_state_machine/shotplan_drill_redrill_cycle
        """
        site = create_site()
        post_bond(site["id"], amount_usd=100000)
        bench = create_released_bench(site["id"])
        plan = create_approved_plan(bench["id"])
        validate_success(api.start_drilling(plan["id"], FOREMAN))
        plan = validate_success(api.complete_drilling(
            plan["id"], {"drilled_hole_count": 20}, FOREMAN))
        assert plan["status"] == "DRILLED"
        plan = validate_success(api.redrill_shot_plan(plan["id"], FOREMAN))
        assert plan["status"] == "DRILLING"
        assert plan["drilled_hole_count"] == 0

    def test_shotplan_drill_redrill_cycle_repeatable(self, api):
        """PRD 3.3: "Collapsed or flooded holes reopen the loop: a redrill
        returns the plan `DRILLED` → `DRILLING` ... and resets
        `drilled_hole_count` to zero." After the reset, a fresh
        complete-drilling report returns the plan to `DRILLED`.

        Design: Difficulty/non_linear_state_machine/shotplan_drill_redrill_cycle
        """
        site = create_site()
        post_bond(site["id"], amount_usd=100000)
        bench = create_released_bench(site["id"])
        plan = create_approved_plan(bench["id"])
        validate_success(api.start_drilling(plan["id"], FOREMAN))
        validate_success(api.complete_drilling(
            plan["id"], {"drilled_hole_count": 20}, FOREMAN))
        validate_success(api.redrill_shot_plan(plan["id"], FOREMAN))
        plan = validate_success(api.complete_drilling(
            plan["id"], {"drilled_hole_count": 20}, FOREMAN))
        assert plan["status"] == "DRILLED"
        assert plan["drilled_hole_count"] == 20


class TestShotPlanApprovalGates:
    def test_sod_shotplan_approve_same_user_rejected(self, api):
        """PRD 2.10: "A shot plan may not be approved by the operator who
        submitted it. ... Each violation is rejected with
        `ERR_SOD_VIOLATION` (403)."

        Design: Corner/validations/sod_shotplan_approve_same_user_rejected
        """
        site = create_site()
        post_bond(site["id"], amount_usd=100000)
        bench = create_released_bench(site["id"])
        plan = create_shot_plan(bench["id"])
        submit_plan(plan["id"])
        # The submitter (X-User-ID bf-1) wears the SiteManager hat here.
        resp = api.approve_shot_plan(plan["id"],
                                     make_site_manager_headers("bf-1"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        assert get_shot_plan(plan["id"])["status"] == "SUBMITTED"

    def test_blast_foreman_cannot_approve_shotplan(self, api):
        """PRD 2.1: "A request whose role is not authorized for the target
        endpoint is rejected with `ERR_FORBIDDEN` (403)."
        PRD 4: POST /shot-plans/{id}/approve is authorized for SiteManager.

        Design: Corner/rbac/blast_foreman_cannot_approve_shotplan
        """
        site = create_site()
        post_bond(site["id"], amount_usd=100000)
        bench = create_released_bench(site["id"])
        plan = create_shot_plan(bench["id"])
        submit_plan(plan["id"])
        resp = api.approve_shot_plan(plan["id"], FOREMAN)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_shot_plan(plan["id"])["status"] == "SUBMITTED"

    def test_approve_requires_bench_released(self, api):
        """PRD 3.3: "Approval by a `SiteManager` moves it `SUBMITTED` →
        `APPROVED` under three gates: the bench must stand `RELEASED`
        (`ERR_BENCH_NOT_RELEASED`), the site posture must be `OPERATING` or
        `RESTRICTED` (`ERR_SITE_POSTURE_BLOCKED`), and the approver must not
        be the operator recorded as the submitter (`ERR_SOD_VIOLATION`)."

        Design: Corner/validations/approve_requires_bench_released
        """
        site = create_site()
        bench = create_bench(site["id"])  # stays PLANNED
        plan = create_shot_plan(bench["id"])
        submit_plan(plan["id"])
        resp = api.approve_shot_plan(plan["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_BENCH_NOT_RELEASED)
        assert get_shot_plan(plan["id"])["status"] == "SUBMITTED"

    def test_holes_incomplete_rejected(self, api):
        """PRD 3.3: "`DRILLING` → `DRILLED` when the foreman reports
        completion with a payload `drilled_hole_count` that must reach at
        least the designed `hole_count` (`ERR_HOLES_INCOMPLETE`, 422, when
        it falls short); the reported count is stored."

        Design: Corner/validations/holes_incomplete_rejected
        """
        site = create_site()
        post_bond(site["id"], amount_usd=100000)
        bench = create_released_bench(site["id"])
        plan = create_approved_plan(bench["id"])
        validate_success(api.start_drilling(plan["id"], FOREMAN))
        resp = api.complete_drilling(plan["id"], {"drilled_hole_count": 19},
                                     FOREMAN)
        validate_error(resp, ApiErrorId.ERR_HOLES_INCOMPLETE)
        assert get_shot_plan(plan["id"])["status"] == "DRILLING"


class TestFiringGates:
    def _loaded_plan(self, api, bond_amount=100000, with_bond=True):
        site = create_site()
        if with_bond:
            post_bond(site["id"], amount_usd=bond_amount)
        bench = create_released_bench(site["id"])
        plan = create_approved_plan(bench["id"])
        advance_plan_to_loaded(plan["id"])
        return site, bench, plan

    def test_outside_blast_window_rejected(self, api):
        """PRD 3.3: "the shot must fall inside the daily blasting window,
        meaning the current logical-clock UTC hour is at least 8 and
        strictly less than 17 — from 08:00 up to but not including 17:00
        UTC (`ERR_OUTSIDE_BLAST_WINDOW`, 422)."

        Design: Corner/validations/outside_blast_window_rejected
        """
        _site, _bench, plan = self._loaded_plan(api)
        create_training(miner_user_id="bf-1")
        set_clock("2026-08-01T07:59:00Z")
        resp = api.fire_shot_plan(plan["id"], FOREMAN)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_BLAST_WINDOW)
        assert get_shot_plan(plan["id"])["status"] == "LOADED"

    def test_safety_beats_temporal_on_fire_error(self, api):
        """PRD 2.7: "Every request is validated against a fixed sequence of
        rule tiers, and the sequence is part of the contract: when several
        rules fail at once, the rejection returned is the one belonging to
        the earliest tier." Tier 7 (regulatory safety, firing training)
        precedes tier 8 (temporal, the blasting window).
        PRD 3.9: "without one the firing is rejected with
        `ERR_TRAINING_EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_fire
        """
        _site, _bench, plan = self._loaded_plan(api)
        # Expired training: completed 2025-06-01 -> expires 2026-06-01, and
        # the current logical date is 2026-08-01.
        create_training(miner_user_id="bf-1", completed_on="2025-06-01")
        # 02:00 UTC is also outside the [8, 17) blasting window.
        set_clock("2026-08-01T02:00:00Z")
        resp = api.fire_shot_plan(plan["id"], FOREMAN)
        validate_error(resp, ApiErrorId.ERR_TRAINING_EXPIRED)

    def test_safety_beats_temporal_on_fire_no_side_effects(self, api):
        """PRD 3.3: "A successful firing stamps `fired_at` from the logical
        clock, moves the plan to the terminal state `FIRED`, and creates
        exactly one **muckpile** as its child". A rejected firing does none
        of this: the plan stays `LOADED` and no muckpile exists.

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_fire
        """
        _site, _bench, plan = self._loaded_plan(api)
        create_training(miner_user_id="bf-1", completed_on="2025-06-01")
        set_clock("2026-08-01T02:00:00Z")
        validate_error(api.fire_shot_plan(plan["id"], FOREMAN),
                       ApiErrorId.ERR_TRAINING_EXPIRED)
        assert get_shot_plan(plan["id"])["status"] == "LOADED"
        data, _meta = validate_paginated(
            api.list_muckpiles(MANAGER, params={"shot_plan_id": plan["id"]}))
        assert data == []

    def test_fire_requires_site_posture_operating_error(self, api):
        """PRD 3.3: "the site posture must be exactly `OPERATING` — a merely
        `RESTRICTED` site may not blast (`ERR_SITE_POSTURE_BLOCKED`)".

        Design: Difficulty/cross_entity_state_dependency/fire_requires_site_posture_operating
        """
        site, _bench, plan = self._loaded_plan(api, with_bond=False)
        # No bond posted: the release dropped coverage to DEFICIENT.
        site = get_site(site["id"])
        assert site["posture"] == "RESTRICTED"
        assert site["bond_adequacy"] == "DEFICIENT"
        create_training(miner_user_id="bf-1")
        set_clock("2026-08-01T10:00:00Z")
        resp = api.fire_shot_plan(plan["id"], FOREMAN)
        validate_error(resp, ApiErrorId.ERR_SITE_POSTURE_BLOCKED)

    def test_fire_requires_site_posture_operating_plan_stays_loaded(self,
                                                                    api):
        """PRD 3.3: "the site posture must be exactly `OPERATING` — a merely
        `RESTRICTED` site may not blast (`ERR_SITE_POSTURE_BLOCKED`)"; the
        rejected firing leaves the plan in `LOADED`.

        Design: Difficulty/cross_entity_state_dependency/fire_requires_site_posture_operating
        """
        site, _bench, plan = self._loaded_plan(api, with_bond=False)
        assert get_site(site["id"])["posture"] == "RESTRICTED"
        create_training(miner_user_id="bf-1")
        set_clock("2026-08-01T10:00:00Z")
        validate_error(api.fire_shot_plan(plan["id"], FOREMAN),
                       ApiErrorId.ERR_SITE_POSTURE_BLOCKED)
        assert get_shot_plan(plan["id"])["status"] == "LOADED"

    def test_sales_agent_cannot_fire_shotplan(self, api):
        """PRD 2.1: "A request whose role is not authorized for the target
        endpoint is rejected with `ERR_FORBIDDEN` (403)."
        PRD 4: POST /shot-plans/{id}/fire is authorized for BlastForeman.

        Design: Corner/rbac/sales_agent_cannot_fire_shotplan
        """
        _site, _bench, plan = self._loaded_plan(api)
        create_training(miner_user_id="bf-1")
        set_clock("2026-08-01T10:00:00Z")
        resp = api.fire_shot_plan(plan["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_shot_plan(plan["id"])["status"] == "LOADED"


class TestMuckpileCreation:
    def test_muckpile_auto_created_and_reverse_discoverable(self, api):
        """PRD 3.3: "A successful firing stamps `fired_at` from the logical
        clock, moves the plan to the terminal state `FIRED`, and creates
        exactly one **muckpile** as its child: the muckpile records the
        originating `shot_plan_id`, copies `estimated_tons` from the plan,
        opens with `remaining_tons` equal to that estimate and
        `actual_fed_tons` at zero, and stands `OPEN`. The new pile is
        discoverable through the muckpile list filtered by `shot_plan_id`."

        Design: Corner/entities/muckpile_auto_created_and_reverse_discoverable
        """
        ctx = setup_blast_site()
        plan = ctx["plan"]
        assert plan["status"] == "FIRED"
        resp = api.list_muckpiles(MANAGER,
                                  params={"shot_plan_id": plan["id"]})
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        muckpile = data[0]
        assert muckpile["shot_plan_id"] == plan["id"]
        assert muckpile["estimated_tons"] == pytest.approx(3792.6, abs=1e-6)
        assert muckpile["remaining_tons"] == pytest.approx(3792.6, abs=1e-6)
        assert muckpile["actual_fed_tons"] == pytest.approx(0, abs=1e-9)
        assert muckpile["status"] == "OPEN"
