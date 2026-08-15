"""Funding cycles: ranking publication, the strict-stop waterfall,
provisional vs final allocation variants, re-publication OCC, cycle close
cycle-back, and the ranking read (PRD §2.6, §2.7, §3.4)."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    approve_plan,
    assert_cycle_budget_invariant,
    build_certified_request,
    close_cycle,
    create_funding_cycle,
    create_treatment_plan,
    get_funding_cycle,
    get_request,
    publish_ranking,
    set_clock,
    setup_funded,
    submit_plan_for_review,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProvisionalVsFinalAllocation:
    """Same request, two allocation variants: provisional 10750 at publish
    (planning ask 10000), final 12900 at plan approval (estimate 12000)."""

    def _setup(self):
        return setup_funded(
            name="Oak St",
            resident_prefix="dv2",
            requested_budget_cents=10000,
            cycle_budget_total_cents=50000,
        )

    def test_publish_assigns_provisional_allocation(self):
        """PRD §3.4: "For each request, its provisional allocation is its `requested_budget_cents` plus a contingency of seven and a half percent of that amount, rounded half-up to a whole cent — the per-request rounding happens before any summation, as §2.6 requires. If the cycle's `budget_available_cents` is greater than or equal to that allocation — an exact fit funds, the boundary is inclusive — the request becomes `FUNDED`: its `funding_cycle_id` is set to the cycle, its `allocated_cents` takes the computed allocation, and the cycle's committed balance rises while its available balance falls by the same amount."

        Design: Difficulty/dual_variant_calc/budget_allocation_provisional_vs_final_on_plan_approval
        """
        ctx = self._setup()
        req = ctx["request"]
        assert req["status"] == "FUNDED"
        assert req["allocated_cents"] == 10750, (
            f"provisional allocation must be 10000 + 750 = 10750, "
            f"got {req['allocated_cents']}"
        )
        cycle = get_funding_cycle(ctx["cycle"]["id"])
        assert cycle["budget_committed_cents"] == 10750
        assert cycle["budget_available_cents"] == 39250
        assert_cycle_budget_invariant(cycle)

    def test_plan_approval_rebaselines_to_final_allocation(self):
        """PRD §3.5: "Link three re-baselines the funding cycle: the final allocation is the plan's `estimated_cost_cents` plus a contingency of seven and a half percent of that estimate, rounded half-up to a whole cent; the delta between that final allocation and the request's current `allocated_cents` must fit within the cycle's `budget_available_cents`, or the entire approval is rejected with `ERR_REBASELINE_EXCEEDS_BUDGET`."
        PRD §3.5: "Whenever the engineer's estimate differs from the resident's original planning ask, the same request therefore ends the cascade with a different allocation than publication assigned — the budget truth is the approved plan, not the petition-era estimate."

        Design: Difficulty/dual_variant_calc/budget_allocation_provisional_vs_final_on_plan_approval
        """
        ctx = self._setup()
        assert ctx["request"]["allocated_cents"] == 10750
        plan = create_treatment_plan(
            ctx["request"]["id"], "SPEED_HUMP", 12000, "te-1"
        )
        submit_plan_for_review(plan["id"], "te-1")
        approve_plan(plan["id"], "ce-1")

        req = get_request(ctx["request"]["id"])
        assert req["allocated_cents"] == 12900, (
            f"final allocation must be 12000 + 900 = 12900, "
            f"got {req['allocated_cents']}"
        )
        cycle = get_funding_cycle(ctx["cycle"]["id"])
        # delta = 12900 - 10750 = +2150 applied at approval.
        assert cycle["budget_committed_cents"] == 12900
        assert cycle["budget_available_cents"] == 37100
        assert_cycle_budget_invariant(cycle)


class TestPerRequestContingencyRounding:
    """Two identical 1007-cent asks: per-request half-up rounding gives
    76 cents of contingency each, so committed lands on 2166 — one cent more
    than the rejected sum-then-round ordering (2165)."""

    def _setup(self):
        set_clock("2026-08-01T00:00:00Z")
        ctx_a = build_certified_request(
            name="Seg A", resident_prefix="cfb-a", requested_budget_cents=1007
        )
        # Nudge the clock so the created_at tie-break resolves deterministically.
        set_clock("2026-08-01T00:00:01Z")
        ctx_b = build_certified_request(
            name="Seg B", resident_prefix="cfb-b", requested_budget_cents=1007
        )
        cycle = create_funding_cycle(2026, 100000)
        publish_ranking(cycle["id"])
        return ctx_a, ctx_b, cycle

    def test_contingency_rounded_per_request_before_summation(self):
        """PRD §3.4: "Requests are ordered by `certified_score` descending, ties broken by the segment's `crash_count_3yr` descending, and remaining ties by the request's `created_at` ascending — earlier filings first; ranks are then assigned one-based as each request's `citywide_rank`."
        PRD §2.6: "The program's contingency rate is seven and a half percent of the base amount, and it is always rounded half-up to a whole cent per request or per plan before any summation takes place."

        Design: Difficulty/combinatorial_formula/allocation_contingency_per_request_rounding_mode_b
        """
        ctx_a, ctx_b, _ = self._setup()
        req_a = get_request(ctx_a["request"]["id"])
        req_b = get_request(ctx_b["request"]["id"])
        assert req_a["allocated_cents"] == 1083, (
            f"1007 + round_half_up(75.525) = 1083, got {req_a['allocated_cents']}"
        )
        assert req_b["allocated_cents"] == 1083
        assert req_a["status"] == "FUNDED" and req_b["status"] == "FUNDED"
        assert req_a["citywide_rank"] == 1, (
            f"equal scores break ties by earlier created_at: "
            f"A must be rank 1, got {req_a['citywide_rank']}"
        )
        assert req_b["citywide_rank"] == 2

    def test_cycle_committed_sums_per_request_rounded_contingencies(self):
        """PRD §2.6: "The program's contingency rate is seven and a half percent of the base amount, and it is always rounded half-up to a whole cent per request or per plan before any summation takes place. The alternative ordering — summing unrounded contingency amounts across requests and rounding once at the end — is explicitly rejected, because the two orderings can diverge by whole cents."

        Design: Difficulty/combinatorial_formula/allocation_contingency_per_request_rounding_mode_b
        """
        _, _, cycle = self._setup()
        cycle = get_funding_cycle(cycle["id"])
        assert cycle["budget_committed_cents"] == 2166, (
            f"per-request rounding gives 2 x 1083 = 2166 (not 2165), "
            f"got {cycle['budget_committed_cents']}"
        )
        assert_cycle_budget_invariant(cycle)


class TestWaterfallStopRule:
    def test_stop_rule_waitlists_lower_ranks_even_when_they_fit(self):
        """PRD §3.4: "The first request that does not fit stops the walk entirely: that request and every lower-ranked request in the pool become `WAITLISTED`, keeping their assigned `citywide_rank` but receiving an `allocated_cents` of zero, with `funding_cycle_id` left null."

        Design: Corner/calculations/waterfall_stop_rule_waitlists_lower_ranked_even_when_they_fit
        """
        set_clock("2026-08-01T00:00:00Z")
        ctx1 = build_certified_request(
            name="WF S1", resident_prefix="wf1", crash_count_3yr=2,
            requested_budget_cents=10000,
        )
        ctx2 = build_certified_request(
            name="WF S2", resident_prefix="wf2", crash_count_3yr=1,
            requested_budget_cents=9000,
        )
        ctx3 = build_certified_request(
            name="WF S3", resident_prefix="wf3", crash_count_3yr=0,
            requested_budget_cents=100,
        )
        cycle = create_funding_cycle(2026, 20000)
        publish_ranking(cycle["id"])

        req1 = get_request(ctx1["request"]["id"])
        req2 = get_request(ctx2["request"]["id"])
        req3 = get_request(ctx3["request"]["id"])
        # Scores: 70 (60 + 2*5), 65, 60 -> ranks 1, 2, 3.
        assert req1["status"] == "FUNDED" and req1["citywide_rank"] == 1
        assert req1["allocated_cents"] == 10750
        # Rank 2 needs 9675 but only 9250 remains -> the walk stops here.
        assert req2["status"] == "WAITLISTED" and req2["citywide_rank"] == 2
        assert req2["allocated_cents"] == 0
        # Rank 3 would fit (108 <= 9250) but the strict stop blocks it.
        assert req3["status"] == "WAITLISTED" and req3["citywide_rank"] == 3
        assert req3["allocated_cents"] == 0

        cycle = get_funding_cycle(cycle["id"])
        assert cycle["budget_committed_cents"] == 10750
        assert cycle["budget_available_cents"] == 9250
        assert_cycle_budget_invariant(cycle)


class TestCycleCloseCycleBack:
    def test_waitlisted_request_cycles_back_on_close(self):
        """PRD §3.4: "Closing a cycle is permitted only from `RANKING_PUBLISHED` — otherwise `ERR_CYCLE_INVALID_STATE` — and moves the cycle to `CLOSED`; every request the cycle left `WAITLISTED` cycles back to `RANKING_ELIGIBLE` with its `citywide_rank` cleared, ready for a future cycle, while `FUNDED` requests keep their allocation untouched."

        Design: Corner/state_machines/waitlisted_request_cycles_back_on_close
        """
        set_clock("2026-08-01T00:00:00Z")
        ctx1 = build_certified_request(
            name="WL S1", resident_prefix="wl1", crash_count_3yr=1
        )
        ctx2 = build_certified_request(
            name="WL S2", resident_prefix="wl2", crash_count_3yr=0
        )
        cycle = create_funding_cycle(2026, 11000)
        publish_ranking(cycle["id"])

        req2 = get_request(ctx2["request"]["id"])
        assert req2["status"] == "WAITLISTED", (
            f"score 60 loses to 65 and 11000 fits only 10750: "
            f"expected WAITLISTED, got {req2['status']}"
        )
        assert req2["citywide_rank"] == 2

        close_cycle(cycle["id"])
        req2 = get_request(ctx2["request"]["id"])
        assert req2["status"] == "RANKING_ELIGIBLE", (
            f"close must cycle WAITLISTED back to RANKING_ELIGIBLE, "
            f"got {req2['status']}"
        )
        assert req2["citywide_rank"] is None, (
            f"citywide_rank must be cleared on cycle-back, "
            f"got {req2['citywide_rank']}"
        )
        req1 = get_request(ctx1["request"]["id"])
        assert req1["status"] == "FUNDED", (
            f"close must not disturb FUNDED requests, got {req1['status']}"
        )


class TestRankingRead:
    def test_ranking_read_returns_rows_rank_ascending(self):
        """PRD §3.4: "The latest publication remains inspectable: a computed read over a cycle returns the requests it most recently considered — the `FUNDED` and `WAITLISTED` rows — sorted by `citywide_rank` ascending."

        Design: Corner/endpoints/ranking_read_returns_ranked_rows_in_order
        """
        set_clock("2026-08-01T00:00:00Z")
        ctx1 = build_certified_request(
            name="Rank S1", resident_prefix="rnk1", crash_count_3yr=1
        )
        ctx2 = build_certified_request(
            name="Rank S2", resident_prefix="rnk2", crash_count_3yr=0
        )
        cycle = create_funding_cycle(2026, 100000)
        publish_ranking(cycle["id"])

        rows, _ = validate_paginated(
            api_client.get_cycle_ranking(cycle["id"], ADMIN)
        )
        assert len(rows) == 2
        assert rows[0]["id"] == ctx1["request"]["id"], (
            "the 65-point request (crash 1) must be the first row"
        )
        assert rows[0]["citywide_rank"] == 1
        assert rows[1]["id"] == ctx2["request"]["id"]
        assert rows[1]["citywide_rank"] == 2


class TestPublishPreconditions:
    def test_publish_with_no_eligible_requests_rejected(self):
        """PRD §3.4: "And the eligible pool must be non-empty: on a first publication, at least one request citywide must be `RANKING_ELIGIBLE`, while on a re-publication the pool is every `RANKING_ELIGIBLE` request citywide plus this cycle's own `WAITLISTED` requests returning for another chance — an empty pool fails with `ERR_NO_ELIGIBLE_REQUESTS`."

        Design: Corner/validations/publish_with_no_eligible_requests_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        cycle = create_funding_cycle(2026, 50000)
        resp = api_client.publish_ranking(
            cycle["id"],
            {"expected_funding_cycle_version": cycle["version"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_REQUESTS)
        after = get_funding_cycle(cycle["id"])
        assert after["status"] == "OPEN", (
            f"a rejected publish must not move the cycle, got {after['status']}"
        )
        assert after["version"] == cycle["version"], (
            "a rejected publish must not bump the cycle version"
        )

    def test_publish_closed_cycle_rejected_terminal_lockdown(self):
        """PRD §3.4: "The cycle must be `OPEN` or `RANKING_PUBLISHED` — publishing against a `CLOSED` cycle fails with `ERR_CYCLE_INVALID_STATE`."

        Design: Corner/state_machines/publish_closed_cycle_rejected_terminal_lockdown
        """
        ctx = setup_funded(name="Lock Ave", resident_prefix="lck")
        close_cycle(ctx["cycle"]["id"])
        closed = get_funding_cycle(ctx["cycle"]["id"])
        assert closed["status"] == "CLOSED"
        resp = api_client.publish_ranking(
            ctx["cycle"]["id"],
            {"expected_funding_cycle_version": closed["version"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CYCLE_INVALID_STATE)

    def test_duplicate_cycle_year_rejected(self):
        """PRD §3.4: "A `CityAdmin` creates a funding cycle with a `cycle_year`, which must be unique across all cycles — a duplicate year is rejected with `ERR_DUPLICATE_CYCLE_YEAR` — and a `budget_total_cents` that must be greater than zero."

        Design: Corner/errors/duplicate_cycle_year_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        create_funding_cycle(2026, 50000)
        resp = api_client.create_funding_cycle(
            {"cycle_year": 2026, "budget_total_cents": 99999},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CYCLE_YEAR)


class TestRankingPublishOcc:
    def test_stale_cycle_version_rejected_on_republish(self):
        """PRD §2.7: "Publishing or re-publishing a funding-cycle ranking requires `expected_funding_cycle_version`, carrying the client's last observed `version` of the cycle; each successful publication re-ranks the citywide list, re-runs the allocation waterfall, and advances the cycle's version, so a publication based on an outdated view is likewise rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.4: "Re-publication supersedes the prior ranking rather than stacking on it. This cycle's `WAITLISTED` requests return to the pool and are re-ranked alongside every `RANKING_ELIGIBLE` request citywide, while requests previously `FUNDED` under the cycle keep their allocation and are excluded from re-ranking entirely."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_ranking_republish
        """
        set_clock("2026-08-01T00:00:00Z")
        ctx1 = build_certified_request(name="Repub S1", resident_prefix="rep1")
        set_clock("2026-08-01T00:00:01Z")
        ctx2 = build_certified_request(name="Repub S2", resident_prefix="rep2")
        cycle = create_funding_cycle(2026, 11000)
        v0 = cycle["version"]

        published = validate_success(
            api_client.publish_ranking(
                cycle["id"], {"expected_funding_cycle_version": v0}, ADMIN
            ),
            200,
        )
        v1 = published["version"]
        assert v1 > v0

        stale = api_client.publish_ranking(
            cycle["id"], {"expected_funding_cycle_version": v0}, ADMIN
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        republished = validate_success(
            api_client.publish_ranking(
                cycle["id"], {"expected_funding_cycle_version": v1}, ADMIN
            ),
            200,
        )
        assert republished["status"] == "RANKING_PUBLISHED"
        assert republished["version"] == v1 + 1, (
            "a successful re-publication must advance the cycle version again"
        )

        req1 = get_request(ctx1["request"]["id"])
        req2 = get_request(ctx2["request"]["id"])
        assert req1["status"] == "FUNDED", (
            "the previously FUNDED request keeps its allocation across "
            f"re-publication, got {req1['status']}"
        )
        assert req1["allocated_cents"] == 10750
        assert req2["status"] == "WAITLISTED", (
            f"the budget still cannot fit the second request, "
            f"got {req2['status']}"
        )
