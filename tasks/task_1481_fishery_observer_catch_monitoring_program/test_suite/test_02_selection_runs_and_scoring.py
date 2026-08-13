"""Coverage-plan publication, selection runs, vessel scoring, and OCC on the
plan version."""
import pytest

from test_helpers import (
    ApiErrorId,
    accept_notice,
    assert_notice_day_invariant,
    assert_selection_notice,
    assert_selection_run,
    get_notice_for_vessel,
    make_coverage_plan,
    make_fishery,
    make_operator,
    make_vessel,
    publish_plan,
    run_selection,
    validate_error,
    validate_paginated,
    validate_success,
)


def _setup_two_gear_vessels(api):
    """Fishery (priority gear TRAWL, target 0.30) + one operator + two ACTIVE
    vessels (TRAWL and LONGLINE) + plan projected 1000/0 published."""
    fishery = make_fishery(
        code="BSAI-GEAR", coverage_target_pct=0.30, priority_gear="TRAWL"
    )
    operator = make_operator()
    v1 = make_vessel(operator, fishery, length_ft=60, gear_type="TRAWL")
    v2 = make_vessel(operator, fishery, length_ft=60, gear_type="LONGLINE")
    plan = make_coverage_plan(
        fishery, projected_fleet_effort_days=1000, projected_em_effort_days=0
    )
    published = publish_plan(plan["id"])
    return fishery, operator, v1, v2, plan, published


class TestSelectionScoringGearBranch:
    def test_scoring_components_and_gear_multiplier(self, api, coordinator_headers):
        """PRD §3.3: "Each surviving vessel is then scored on three components.
        The recency component rewards time away from observation: count the
        whole days between the vessel's `last_observed_end_date` and the plan's
        `period_start` — a never-observed vessel counts 365 days — cap that
        count at 365, express it as a fraction of 365, and multiply by a weight
        of 50. The compliance component is 30 when the vessel's
        `substantiated_harassment_count` is zero, and otherwise 30 less 10
        points per substantiated report, never dropping below zero. The penalty
        component is 5 points for every point of the vessel's
        `selection_penalty_points`. The raw score is the recency component plus
        the compliance component minus the penalty component; when the vessel's
        `gear_type` equals the fishery's `priority_gear`, the raw score is then
        multiplied by 1.25."

        Design: Difficulty/combinatorial_formula/selection_scoring_multi_input_nonlinear_with_gear_branch
        """
        fishery, operator, v1, v2, plan, published = _setup_two_gear_vessels(api)
        assert published["required_observer_sea_days"] == 300

        run = run_selection(plan["id"])
        n1 = get_notice_for_vessel(plan["id"], v1["id"])
        n2 = get_notice_for_vessel(plan["id"], v2["id"])
        # Vessel 1: recency 50 (never observed) + compliance 30 - penalty 0,
        # then the TRAWL gear match multiplies by 1.25 -> 100.0000.
        assert n1["selection_score"] == pytest.approx(100.0, abs=1e-4)
        assert n1["rank"] == 1
        # Vessel 2: identical inputs but LONGLINE != TRAWL -> no multiplier.
        assert n2["selection_score"] == pytest.approx(80.0, abs=1e-4)
        assert n2["rank"] == 2
        assert run["vessels_evaluated"] == 2

    def test_run_sizing_and_deficit_and_notice_minting(self, api, coordinator_headers):
        """PRD §3.3: "The run sizes itself from the requirement: the number of
        vessels to select is `required_observer_sea_days` divided by the 30-day
        notice allocation, rounded up to a whole number, and the run takes the
        top-ranked vessels up to that count, or the whole eligible pool when
        the pool is smaller." and "Every selected vessel receives exactly one
        **selection notice** in `ISSUED` status, carrying `allocated_sea_days`
        of 30, `reserved_sea_days` and `consumed_sea_days` of zero,
        `remaining_sea_days` of 30, its `selection_score`, its 1-based `rank`
        within the run, and a `response_deadline` copied from the run's
        `notice_response_deadline`."

        Design: Difficulty/combinatorial_formula/selection_scoring_multi_input_nonlinear_with_gear_branch
        """
        fishery, operator, v1, v2, plan, published = _setup_two_gear_vessels(api)
        deadline = "2026-09-20T00:00:00Z"
        run = run_selection(plan["id"], notice_response_deadline=deadline)
        assert_selection_run(run)
        assert run["vessels_selected"] == 2
        # vessels_to_select = ceil(300 / 30) = 10 > pool of 2 -> deficit.
        assert run["selection_deficit_sea_days"] == 240

        for vessel in (v1, v2):
            notice = get_notice_for_vessel(plan["id"], vessel["id"])
            assert_selection_notice(notice)
            assert notice["status"] == "ISSUED"
            assert notice["allocated_sea_days"] == 30
            assert notice["reserved_sea_days"] == 0
            assert notice["consumed_sea_days"] == 0
            assert notice["remaining_sea_days"] == 30
            assert_notice_day_invariant(notice)
            assert notice["response_deadline"] is not None


class TestSelectionRunSizingEdgeCases:
    def test_empty_eligible_pool_is_not_an_error(self, api, coordinator_headers):
        """PRD §3.3: "An empty eligible pool is not an error: the run simply
        completes with `vessels_selected` at zero and the deficit equal to the
        entire requirement."

        Design: Corner/calculations/selection_sizing_empty_eligible_pool_not_an_error
        """
        fishery = make_fishery(code="BSAI-ES")
        plan = make_coverage_plan(
            fishery, projected_fleet_effort_days=100, projected_em_effort_days=0
        )
        publish_plan(plan["id"])
        resp = api.create_selection_run(
            plan["id"],
            {
                "notice_response_deadline": "2026-09-20T00:00:00Z",
                "expected_coverage_plan_version": validate_success(
                    api.get_coverage_plan(plan["id"], coordinator_headers)
                )["version"],
            },
            coordinator_headers,
        )
        run = validate_success(resp, 201)
        assert run["vessels_evaluated"] == 0
        assert run["vessels_selected"] == 0
        assert run["selection_deficit_sea_days"] == 30

        notices, _ = validate_paginated(
            api.list_selection_notices(
                coordinator_headers, params={"selection_run_id": run["id"]}
            )
        )
        assert notices == []
        plan = validate_success(api.get_coverage_plan(plan["id"], coordinator_headers))
        assert plan["status"] == "SELECTION_COMPLETED"

    def test_backfill_run_excludes_vessels_with_open_notices(self, api, coordinator_headers):
        """PRD §3.3: "A vessel may be scored only when all of the following
        hold: the vessel is `ACTIVE`; its `monitoring_mode` is `HUMAN_OBSERVER`;
        its `fishery_id` matches the plan's fishery; its operator's
        `payment_standing` is `GOOD`; and the vessel holds no notice in
        `ISSUED` or `ACCEPTED` under this plan — the clause that keeps backfill
        runs from double-notifying a vessel already in play." and "The first
        run requires the plan in `PUBLISHED` and moves it to
        `SELECTION_COMPLETED`; backfill runs may follow while the plan remains
        in `SELECTION_COMPLETED`."

        Design: Corner/calculations/selection_scoring_excludes_vessels_with_open_notice_on_backfill
        """
        fishery = make_fishery(code="BSAI-BF", priority_gear="TRAWL")
        operator = make_operator()
        v1 = make_vessel(operator, fishery, length_ft=55, gear_type="TRAWL")
        v2 = make_vessel(operator, fishery, length_ft=55, gear_type="LONGLINE")
        plan = make_coverage_plan(
            fishery, projected_fleet_effort_days=1000, projected_em_effort_days=0
        )
        publish_plan(plan["id"])
        run1 = run_selection(plan["id"])
        n1 = get_notice_for_vessel(plan["id"], v1["id"])
        # V1 answers (ACCEPTED); V2's notice stays ISSUED — both are "open".
        accept_notice(n1["id"], operator["id"])

        # V3 registers only after run 1.
        v3 = make_vessel(operator, fishery, length_ft=55, gear_type="TRAWL")
        run2 = run_selection(plan["id"], notice_response_deadline="2026-09-25T00:00:00Z")
        assert run2["run_index"] == 2
        assert run2["vessels_evaluated"] == 1
        assert run2["vessels_selected"] == 1
        notices, _ = validate_paginated(
            api.list_selection_notices(
                coordinator_headers, params={"selection_run_id": run2["id"]}
            )
        )
        assert len(notices) == 1
        assert notices[0]["vessel_id"] == v3["id"]
        plan = validate_success(api.get_coverage_plan(plan["id"], coordinator_headers))
        assert plan["status"] == "SELECTION_COMPLETED"

    def test_tie_broken_by_created_at_not_id(self, api, coordinator_headers):
        """PRD §3.3: "Vessels are ranked by score descending; ties break first
        by `last_observed_end_date` ascending with never-observed vessels
        ranking ahead of all dated ones, then by the vessel's `created_at`
        ascending — the vessel's `id` must never be consulted for ranking."

        Design: Corner/cross_cutting_layers/selector_policy_deterministic_ranking_tiebreak
        """
        fishery = make_fishery(code="BSAI-TIE", priority_gear="POT")
        operator = make_operator()
        va = make_vessel(operator, fishery, length_ft=55, gear_type="LONGLINE")
        vb = make_vessel(operator, fishery, length_ft=55, gear_type="LONGLINE")
        plan = make_coverage_plan(
            fishery, projected_fleet_effort_days=200, projected_em_effort_days=0
        )
        publish_plan(plan["id"])
        run_selection(plan["id"])
        na = get_notice_for_vessel(plan["id"], va["id"])
        nb = get_notice_for_vessel(plan["id"], vb["id"])
        # Identical scores (LONGLINE != POT, so no gear multiplier): the
        # earlier-registered vessel must take rank 1.
        assert na["selection_score"] == pytest.approx(80.0, abs=1e-4)
        assert nb["selection_score"] == pytest.approx(80.0, abs=1e-4)
        assert na["rank"] == 1
        assert nb["rank"] == 2


class TestPlanVersionOCC:
    def test_selection_run_stale_plan_version_rejected(self, api, coordinator_headers):
        """PRD §2.8: "Launching a selection run requires
        `expected_coverage_plan_version`, matched against the coverage plan's
        current `version`; a mismatch — the plan was just published, or an
        earlier run just completed and changed the requirement or the
        eligibility base — is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_selection_run_stale_plan_version
        """
        fishery = make_fishery(code="BSAI-OC2")
        plan = make_coverage_plan(
            fishery, projected_fleet_effort_days=100, projected_em_effort_days=0
        )
        stale_version = plan["version"]
        published = publish_plan(plan["id"])
        fresh_version = published["version"]
        assert fresh_version != stale_version

        stale = api.create_selection_run(
            plan["id"],
            {
                "notice_response_deadline": "2026-09-20T00:00:00Z",
                "expected_coverage_plan_version": stale_version,
            },
            coordinator_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

        fresh = api.create_selection_run(
            plan["id"],
            {
                "notice_response_deadline": "2026-09-20T00:00:00Z",
                "expected_coverage_plan_version": fresh_version,
            },
            coordinator_headers,
        )
        run = validate_success(fresh, 201)
        assert run["coverage_plan_id"] == plan["id"]
        plan = validate_success(api.get_coverage_plan(plan["id"], coordinator_headers))
        assert plan["status"] == "SELECTION_COMPLETED"


class TestFisheryActiveGate:
    def test_publish_rejected_when_fishery_suspended(self, api, admin_headers, coordinator_headers):
        """PRD §3.2: "A coordinator may publish only while the fishery is
        `ACTIVE` — publishing against a suspended fishery yields
        `ERR_FISHERY_NOT_ACTIVE`"

        Design: Difficulty/cross_entity_state_dependency/coverage_plan_publish_gated_on_fishery_active
        """
        fishery = make_fishery(code="BSAI-X1")
        plan = make_coverage_plan(
            fishery, projected_fleet_effort_days=100, projected_em_effort_days=0
        )
        validate_success(
            api.patch_fishery(fishery["id"], {"status": "SUSPENDED"}, admin_headers)
        )
        resp = api.publish_coverage_plan(plan["id"], {}, coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_FISHERY_NOT_ACTIVE, 409)
        plan = validate_success(api.get_coverage_plan(plan["id"], coordinator_headers))
        assert plan["status"] == "DRAFT", "no transition may occur on the failed publish"

    def test_selection_run_rejected_when_fishery_suspended(self, api, admin_headers, coordinator_headers):
        """PRD §3.3: "A run attempted against a plan still in `DRAFT` is
        rejected with `ERR_PLAN_NOT_PUBLISHED`, a run against a plan in any
        other non-runnable state is rejected with `ERR_INVALID_STATE`, and in
        every case the fishery must be `ACTIVE` or the run fails with
        `ERR_FISHERY_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/coverage_plan_publish_gated_on_fishery_active
        """
        fishery = make_fishery(code="BSAI-X1B")
        plan = make_coverage_plan(
            fishery, projected_fleet_effort_days=100, projected_em_effort_days=0
        )
        publish_plan(plan["id"])
        validate_success(
            api.patch_fishery(fishery["id"], {"status": "SUSPENDED"}, admin_headers)
        )
        plan_now = validate_success(api.get_coverage_plan(plan["id"], coordinator_headers))
        resp = api.create_selection_run(
            plan["id"],
            {
                "notice_response_deadline": "2026-09-20T00:00:00Z",
                "expected_coverage_plan_version": plan_now["version"],
            },
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FISHERY_NOT_ACTIVE, 409)
        plan = validate_success(api.get_coverage_plan(plan["id"], coordinator_headers))
        assert plan["status"] == "PUBLISHED", "no run may be created against a suspended fishery"

    def test_selection_run_against_draft_plan_rejected(self, api, coordinator_headers):
        """PRD §3.3: "A run attempted against a plan still in `DRAFT` is
        rejected with `ERR_PLAN_NOT_PUBLISHED`, a run against a plan in any
        other non-runnable state is rejected with `ERR_INVALID_STATE`, and in
        every case the fishery must be `ACTIVE` or the run fails with
        `ERR_FISHERY_NOT_ACTIVE`."

        Design: Corner/validations/plan_close_and_selection_run_state_gate_errors
        """
        fishery = make_fishery(code="BSAI-PNP")
        plan = make_coverage_plan(
            fishery, projected_fleet_effort_days=100, projected_em_effort_days=0
        )
        resp = api.create_selection_run(
            plan["id"],
            {
                "notice_response_deadline": "2026-09-20T00:00:00Z",
                "expected_coverage_plan_version": plan["version"],
            },
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_PUBLISHED, 409)
        plan = validate_success(api.get_coverage_plan(plan["id"], coordinator_headers))
        assert plan["status"] == "DRAFT"
        runs, _ = validate_paginated(
            api.list_selection_runs(plan["id"], coordinator_headers)
        )
        assert runs == []
