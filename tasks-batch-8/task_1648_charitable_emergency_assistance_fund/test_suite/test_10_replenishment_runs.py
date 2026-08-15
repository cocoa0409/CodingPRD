"""Waitlist replenishment sweeps: pinned evaluation order, promotion cascade,
eligibility-lapse denial via policy swap, and candidate-count conservation."""
from test_helpers import (
    ApiErrorId,
    assert_replenishment_run,
    build_pending_decision_on_existing_vendor,
    create_active_policy,
    create_funding_source,
    create_policy_payload,
    deposit,
    get_application,
    list_award_allocations,
    run_replenishment,
    set_clock,
    setup_pending_decision,
    TEST_USERS,
    validate_error,
    validate_success,
    waitlist_application,
)

PM1 = TEST_USERS["program_manager_headers"]
AUD1 = TEST_USERS["auditor_headers"]


def _waitlist_after_failed_approve(api, ctx):
    """Attempt a direct approve (expected to fail on funds) then waitlist."""
    resp = api.approve_application(ctx["application"]["id"], PM1)
    validate_error(resp, ApiErrorId.ERR_FUNDS_EXHAUSTED)
    return waitlist_application(ctx["application"]["id"])


class TestEmptyRun:
    def test_replenishment_run_on_empty_waitlist_is_noop(self, api):
        """PRD §3.8: "The run sweeps every application in `WAITLISTED` status at
        run start, snapshotted and ordered once by `waitlisted_at` ascending with
        ties broken by `created_at` ascending — never by id; applications that
        enter the waitlist mid-run are not included."
        PRD §3.8: "Conservation holds across every run: the number of waitlisted
        candidates before the run equals `promoted_count` plus `denied_count`
        plus `remaining_waitlisted_count`."

        Design: Corner/endpoints/replenishment_run_on_empty_waitlist_is_noop
        """
        create_active_policy()
        resp = api.create_replenishment_run(PM1)
        run = validate_success(resp, 201)
        assert_replenishment_run(run)
        assert run["promoted_count"] == 0
        assert run["denied_count"] == 0
        assert run["remaining_waitlisted_count"] == 0
        assert run["promoted_application_ids"] == []
        assert run["denied_application_ids"] == []


class TestPromotionEvaluationOrder:
    def _two_candidate_setup(self, api):
        """W1 (50000, waitlisted first) and W2 (15000, second) against source C
        with only 10000 budget; a 50000 deposit lands before the run."""
        ctx1 = setup_pending_decision(
            requested_amount_cents=50000,
            policy_overrides={"rent_cap_cents": 60000},
            household_overrides={
                "head_of_household_name": "Eva Park", "annual_income_cents": 1000000,
            },
            source_overrides={
                "name": "C", "funder_name": "Funder C",
                "source_type": "GRANT_RESTRICTED", "allowed_categories": ["RENT"],
                "total_budget_cents": 10000,
            },
        )
        w1 = _waitlist_after_failed_approve(api, ctx1)
        ctx2 = build_pending_decision_on_existing_vendor(
            ctx1["vendor"]["id"],
            requested_amount_cents=15000,
            household_overrides={
                "head_of_household_name": "Fred Lane", "annual_income_cents": 1000000,
            },
            clock="2026-08-02T00:00:00Z",
        )
        w2 = _waitlist_after_failed_approve(api, ctx2)
        deposit(ctx1["source"]["id"], 50000)  # available rises to 60000
        return ctx1, w1, ctx2, w2

    def test_older_waitlisted_promotes_even_when_later_would_fit(self, api):
        """PRD §3.8: "Each candidate is then processed strictly in order, and the
        evaluation order is pinned: a candidate's own reservation is never part
        of the availability it is checked against — availability is read before
        the candidate commits, and its commit lands before the next candidate is
        evaluated."
        PRD §3.8: "The run sweeps every application in `WAITLISTED` status at run
        start, snapshotted and ordered once by `waitlisted_at` ascending with
        ties broken by `created_at` ascending — never by id; applications that
        enter the waitlist mid-run are not included."

        Design: Difficulty/combinatorial_formula/promotion_availability_evaluated_before_own_reservation
        """
        _, w1, _, w2 = self._two_candidate_setup(api)
        run = run_replenishment()
        assert run["promoted_count"] == 1
        assert run["denied_count"] == 0
        assert run["remaining_waitlisted_count"] == 1
        assert run["promoted_application_ids"] == [w1["id"]], (
            "waitlisted_at order is pinned — not fit-sorted"
        )
        assert get_application(w1["id"])["status"] == "APPROVED"
        assert get_application(w2["id"])["status"] == "WAITLISTED", (
            "W2's smaller request does not jump the queue: W1's commit lands first"
        )

    def test_failed_direct_approvals_are_atomic_then_balances_reflect_run(self, api):
        """PRD §3.5: "If the sweep ends with need still uncovered, the approval
        is rejected with `ERR_FUNDS_EXHAUSTED` (HTTP 402) and the operation is
        atomic — no award, no allocations, and no balance changes persist."
        PRD §3.8: "A candidate that clears all three steps is promoted
        `WAITLISTED → APPROVED`: its `policy_id` is re-pinned to the currently
        `ACTIVE` policy, and the award, allocations, source balance updates, and
        automatic `EXHAUSTED` transitions all commit exactly as in a direct
        approval, with the application's `version` bumping."

        Design: Difficulty/combinatorial_formula/promotion_availability_evaluated_before_own_reservation
        """
        ctx1, w1, _, w2 = self._two_candidate_setup(api)
        # The failed direct approves reserved nothing.
        before = validate_success(api.get_funding_source(ctx1["source"]["id"], PM1), 200)
        assert before["reserved_cents"] == 0
        assert before["available_cents"] == 60000
        run_replenishment()
        after = validate_success(api.get_funding_source(ctx1["source"]["id"], PM1), 200)
        assert after["reserved_cents"] == 50000  # only W1's award reserved
        assert after["available_cents"] == 10000
        assert get_application(w2["id"])["status"] == "WAITLISTED"


class TestPromotionCascade:
    def _single_candidate_setup(self, api):
        """Source F starts at 5000; a 45000 request waitlists; a 40000 deposit
        raises availability to exactly 45000 before the run."""
        ctx = setup_pending_decision(
            requested_amount_cents=45000,
            source_overrides={
                "name": "F", "funder_name": "Funder F",
                "source_type": "GRANT_RESTRICTED", "allowed_categories": ["RENT"],
                "total_budget_cents": 5000,
            },
            household_overrides={
                "head_of_household_name": "Kai Moss", "annual_income_cents": 900000,
            },
        )
        waitlisted = _waitlist_after_failed_approve(api, ctx)
        deposit(ctx["source"]["id"], 40000)
        return ctx, waitlisted

    def test_run_promotes_and_drains_source_to_exhausted(self, api):
        """PRD §3.8: "A candidate that clears all three steps is promoted
        `WAITLISTED → APPROVED`: its `policy_id` is re-pinned to the currently
        `ACTIVE` policy, and the award, allocations, source balance updates, and
        automatic `EXHAUSTED` transitions all commit exactly as in a direct
        approval, with the application's `version` bumping."
        PRD §3.1: "A source whose `available_cents` reaches exactly zero after
        any reservation or budget mutation automatically transitions `ACTIVE →
        EXHAUSTED`"

        Design: Difficulty/transitive_cascade/replenishment_promotion_cascade
        """
        ctx, waitlisted = self._single_candidate_setup(api)
        run = run_replenishment()
        assert run["promoted_count"] == 1
        application = get_application(waitlisted["id"])
        assert application["status"] == "APPROVED"
        award = validate_success(
            api.get_award(application["active_award_id"], PM1), 200
        )
        assert award["awarded_amount_cents"] == 45000
        allocations = list_award_allocations(award["id"])
        assert len(allocations) == 1
        assert allocations[0]["funding_source_id"] == ctx["source"]["id"]
        assert allocations[0]["allocated_cents"] == 45000
        assert allocations[0]["status"] == "RESERVED"
        source = validate_success(api.get_funding_source(ctx["source"]["id"], PM1), 200)
        assert source["reserved_cents"] == 45000
        assert source["available_cents"] == 0
        assert source["status"] == "EXHAUSTED"

    def test_run_record_and_failed_approve_atomicity(self, api):
        """PRD §3.8: "The run's results persist on the ReplenishmentRun record:
        the launching manager as `run_by`, the `promoted_count`, the
        `denied_count`, the `remaining_waitlisted_count`, the
        `promoted_application_ids` in promotion order, and the
        `denied_application_ids` in processing order."
        PRD §3.5: "If the sweep ends with need still uncovered, the approval is
        rejected with `ERR_FUNDS_EXHAUSTED` (HTTP 402) and the operation is
        atomic — no award, no allocations, and no balance changes persist."

        Design: Difficulty/transitive_cascade/replenishment_promotion_cascade
        """
        ctx, waitlisted = self._single_candidate_setup(api)
        # The atomic failed approve left the source untouched before the deposit.
        source = validate_success(api.get_funding_source(ctx["source"]["id"], PM1), 200)
        assert source["reserved_cents"] == 0
        run = run_replenishment()
        assert run["promoted_application_ids"] == [waitlisted["id"]]
        assert run["denied_application_ids"] == []
        fetched = validate_success(api.get_replenishment_run(run["id"], AUD1), 200)
        assert fetched["promoted_count"] == 1
        assert fetched["run_by"] == "pm-1"


class TestCandidateCountConservation:
    def _three_candidate_setup(self, api):
        """W1 (income 1000000, 30000, day 1), W2 (income 2000000, 20000, day 2),
        W3 (income 1000000, 20000, day 3); then a stricter policy activates and
        a 35000 deposit lands before the run."""
        ctx1 = setup_pending_decision(
            requested_amount_cents=30000,
            policy_overrides={"name": "PA", "rent_cap_cents": 60000},
            household_overrides={
                "head_of_household_name": "Bob Eder", "annual_income_cents": 1000000,
            },
            source_overrides={
                "name": "T", "funder_name": "Funder T",
                "source_type": "GRANT_RESTRICTED", "allowed_categories": ["RENT"],
                "total_budget_cents": 5000,
            },
        )
        w1 = _waitlist_after_failed_approve(api, ctx1)
        ctx2 = build_pending_decision_on_existing_vendor(
            ctx1["vendor"]["id"],
            requested_amount_cents=20000,
            household_overrides={
                "head_of_household_name": "Cid Farr", "annual_income_cents": 2000000,
            },
            clock="2026-08-02T00:00:00Z",
        )
        w2 = _waitlist_after_failed_approve(api, ctx2)
        ctx3 = build_pending_decision_on_existing_vendor(
            ctx1["vendor"]["id"],
            requested_amount_cents=20000,
            household_overrides={
                "head_of_household_name": "Dee Gorr", "annual_income_cents": 1000000,
            },
            clock="2026-08-03T00:00:00Z",
        )
        w3 = _waitlist_after_failed_approve(api, ctx3)
        # Mid-flight policy swap: income limit drops below W2's income.
        strict = validate_success(
            api.create_policy(
                create_policy_payload(
                    name="PB", rent_cap_cents=60000, income_limit_cents=1500000
                ),
                PM1,
            ),
            201,
        )
        validate_success(api.activate_policy(strict["id"], PM1), 200)
        deposit(ctx1["source"]["id"], 35000)  # available rises to 40000
        return ctx1, w1, w2, w3, strict

    def test_promoted_denied_remaining_counts_conserve(self, api):
        """PRD §3.8: "Conservation holds across every run: the number of
        waitlisted candidates before the run equals `promoted_count` plus
        `denied_count` plus `remaining_waitlisted_count`."
        PRD §3.8: "A candidate the waterfall cannot fully fund remains
        `WAITLISTED` and the run continues to the next candidate —
        skip-and-continue, never stop-at-first-failure."

        Design: Difficulty/compensating_invariant/waitlist_candidate_count_conserved
        """
        _, w1, w2, w3, _ = self._three_candidate_setup(api)
        run = run_replenishment()
        assert run["promoted_count"] == 1
        assert run["denied_count"] == 1
        assert run["remaining_waitlisted_count"] == 1
        assert (
            run["promoted_count"] + run["denied_count"] + run["remaining_waitlisted_count"]
            == 3
        ), "candidates before the run == promoted + denied + remaining"
        assert run["promoted_application_ids"] == [w1["id"]]
        assert run["denied_application_ids"] == [w2["id"]]

    def test_lapsed_denial_reason_and_policy_repin_on_promotion(self, api):
        """PRD §3.8: "First, eligibility is re-screened — income and both caps —
        against the currently `ACTIVE` policy; a candidate that fails moves
        `WAITLISTED → DENIED` with `denial_reason` set to `ELIGIBILITY_LAPSED`
        and `denied_at` stamped."
        PRD §3.8: "A candidate that clears all three steps is promoted
        `WAITLISTED → APPROVED`: its `policy_id` is re-pinned to the currently
        `ACTIVE` policy, and the award, allocations, source balance updates, and
        automatic `EXHAUSTED` transitions all commit exactly as in a direct
        approval, with the application's `version` bumping."

        Design: Difficulty/compensating_invariant/waitlist_candidate_count_conserved
        """
        _, w1, w2, w3, strict = self._three_candidate_setup(api)
        run_replenishment()
        promoted = get_application(w1["id"])
        assert promoted["status"] == "APPROVED"
        assert promoted["policy_id"] == strict["id"], (
            "promotion re-pins the currently ACTIVE policy"
        )
        denied = get_application(w2["id"])
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "ELIGIBILITY_LAPSED", (
            "income 2000000 exceeds the new limit 1500000"
        )
        survivor = get_application(w3["id"])
        assert survivor["status"] == "WAITLISTED", (
            "award 20000 exceeds the 10000 left after W1's promotion"
        )
