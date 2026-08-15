"""Award adjustment (pro-rata release with pinned rounding) and voiding
(compensation cascade, payment guards, re-approval)."""
from test_helpers import (
    ApiErrorId,
    adjust_award_payload,
    approve_application,
    assert_source_balance_invariant,
    clear_payment,
    get_application,
    get_award,
    issue_payment,
    list_application_awards,
    list_award_allocations,
    setup_approved,
    TEST_USERS,
    validate_error,
    validate_success,
    validate_paginated,
)

PM1 = TEST_USERS["program_manager_headers"]
FIN1 = TEST_USERS["finance_officer_headers"]


class TestAwardAdjustmentProration:
    def _proration_setup(self):
        """Award 100000 reserved 30000/30000/40000 across S2 (rank 0),
        S3 (rank 1), S1 (rank 2) — ranked by period_end ascending."""
        ctx = setup_approved(
            requested_amount_cents=100000,
            policy_overrides={
                "max_annual_benefit_cents": 200000,
                "rent_cap_cents": 150000,
            },
            clock="2026-03-01T00:00:00Z",  # inside every source's period
            service_month="2026-08",
            sources=[
                dict(name="S1", funder_name="Funder X", source_type="GRANT_RESTRICTED",
                     allowed_categories=["RENT"],
                     period_start="2026-01-01T00:00:00Z",
                     period_end="2026-12-31T00:00:00Z", total_budget_cents=40000),
                dict(name="S2", funder_name="Funder Y", source_type="GRANT_RESTRICTED",
                     allowed_categories=["RENT"],
                     period_start="2026-01-01T00:00:00Z",
                     period_end="2026-06-30T00:00:00Z", total_budget_cents=30000),
                dict(name="S3", funder_name="Funder Z", source_type="GRANT_RESTRICTED",
                     allowed_categories=["RENT"],
                     period_start="2026-01-01T00:00:00Z",
                     period_end="2026-09-30T00:00:00Z", total_budget_cents=30000),
            ],
        )
        s1, s2, s3 = (s["id"] for s in ctx["sources"])
        allocations = ctx["allocations"]
        assert [(a["funding_source_id"], a["allocated_cents"])
                for a in allocations] == [(s2, 30000), (s3, 30000), (s1, 40000)]
        return ctx, s1, s2, s3

    def test_adjust_releases_floor_per_allocation_remainder_to_last_rank(self, api):
        """PRD §3.6: "For every allocation except the last-ranked one, the
        released amount is that allocation's `allocated_cents` multiplied by the
        reduction and divided by the award's `awarded_amount_cents`, rounded down
        to a whole cent. The last-ranked allocation absorbs the remainder: the
        reduction minus the sum of the earlier releases."
        PRD §3.6: "This rounding order is pinned — per-allocation floor first,
        remainder to the last-ranked allocation — because floor-then-remainder
        and remainder-first produce different per-source releases."

        Design: Difficulty/combinatorial_formula/award_adjust_proration_remainder_to_last_rank
        """
        ctx, s1, s2, s3 = self._proration_setup()
        award = ctx["award"]
        adjusted = validate_success(
            api.adjust_award(award["id"], adjust_award_payload(90001, award["version"]), PM1),
            200,
        )
        assert adjusted["awarded_amount_cents"] == 90001
        allocations = list_award_allocations(award["id"])
        by_source = {a["funding_source_id"]: a for a in allocations}
        # reduction 9999: floor(30000*9999/100000) = 2999 released from each of
        # the first two ranks; the remaining 4001 releases from the last rank.
        assert by_source[s2]["allocated_cents"] == 30000 - 2999
        assert by_source[s3]["allocated_cents"] == 30000 - 2999
        assert by_source[s1]["allocated_cents"] == 40000 - 4001, (
            "the rounding remainder is absorbed by the last-ranked allocation"
        )
        total = sum(a["allocated_cents"] for a in allocations)
        assert total == 90001 == adjusted["awarded_amount_cents"]

    def test_adjust_updates_source_reserved_balances(self, api):
        """PRD §3.6: "Each release lowers the allocation's `allocated_cents` and
        its funding source's `reserved_cents` by the same amount; an allocation
        whose `allocated_cents` falls to zero transitions `RESERVED → RELEASED`;
        and any `EXHAUSTED` source whose `available_cents` rises above zero
        through the release returns automatically to `ACTIVE`."
        PRD §3.1: "the invariant that committed plus reserved plus available
        always equals `total_budget_cents` holds at all times."

        Design: Difficulty/combinatorial_formula/award_adjust_proration_remainder_to_last_rank
        """
        ctx, s1, s2, s3 = self._proration_setup()
        award = ctx["award"]
        # Before adjustment the sweep drained all three sources to zero.
        for sid in (s1, s2, s3):
            source = validate_success(api.get_funding_source(sid, PM1), 200)
            assert source["reserved_cents"] > 0
        validate_success(
            api.adjust_award(award["id"], adjust_award_payload(90001, award["version"]), PM1),
            200,
        )
        expected_reserved = {s2: 27001, s3: 27001, s1: 35999}
        for sid, reserved in expected_reserved.items():
            source = validate_success(api.get_funding_source(sid, PM1), 200)
            assert source["reserved_cents"] == reserved
            assert_source_balance_invariant(source)
        award_after = get_award(award["id"])
        assert award_after["awarded_amount_cents"] == 90001
        assert award_after["version"] == award["version"] + 1


class TestAwardIdentityConservation:
    def _identity_setup(self):
        ctx = setup_approved(
            requested_amount_cents=60000,
            policy_overrides={"rent_cap_cents": 70000},
            sources=[
                dict(name="R", funder_name="Funder R", source_type="GRANT_RESTRICTED",
                     allowed_categories=["RENT"], total_budget_cents=25000),
                dict(name="S", funder_name="Funder S", total_budget_cents=50000),
            ],
        )
        sr, ss = (s["id"] for s in ctx["sources"])
        allocations = ctx["allocations"]
        assert [(a["funding_source_id"], a["allocated_cents"])
                for a in allocations] == [(sr, 25000), (ss, 35000)]
        return ctx, sr, ss

    def test_allocation_sum_identity_holds_through_adjust(self, api):
        """PRD §3.6: "The reduction — the difference between the current
        `awarded_amount_cents` and the requested `new_awarded_amount_cents` — is
        released pro rata across the award's `RESERVED` allocations in ascending
        `rank_order`."
        PRD §3.5: "each take creates a FundingAllocation in `RESERVED` status
        with `consumed_cents` at zero, adds the take to the source's
        `reserved_cents`"

        Design: Difficulty/compensating_invariant/award_allocation_identity_conserved_through_adjust_and_void
        """
        ctx, sr, ss = self._identity_setup()
        award = ctx["award"]
        allocations = ctx["allocations"]
        assert sum(a["allocated_cents"] for a in allocations) == 60000 == award["awarded_amount_cents"]
        adjusted = validate_success(
            api.adjust_award(award["id"], adjust_award_payload(45000, award["version"]), PM1),
            200,
        )
        assert adjusted["awarded_amount_cents"] == 45000
        by_source = {a["funding_source_id"]: a
                     for a in list_award_allocations(award["id"])}
        # reduction 15000: floor(25000*15000/60000) = 6250 from R;
        # remainder 8750 from S (last rank).
        assert by_source[sr]["allocated_cents"] == 18750
        assert by_source[ss]["allocated_cents"] == 26250
        assert by_source[sr]["allocated_cents"] + by_source[ss]["allocated_cents"] == 45000

    def test_void_restores_household_exposure_to_baseline(self, api):
        """PRD §3.9: "the exposure basis counts the full `awarded_amount_cents`
        of every non-`VOIDED` award in the benefit-year set, including
        approved-but-unpaid amounts, while the committed basis counts only
        `consumed_cents` across those awards' allocations — money actually
        cleared — so the two differ whenever an award is approved but not yet
        fully paid."
        PRD §3.6: "A successful void flips every `RESERVED` allocation of the
        award to `RELEASED`, reduces each affected source's `reserved_cents` by
        that allocation's `allocated_cents` minus its `consumed_cents`, revives
        any `EXHAUSTED` source whose availability rises above zero back to
        `ACTIVE`, moves the application `APPROVED → PENDING_DECISION` with its
        `active_award_id` cleared to empty, and increments the award's `version`."

        Design: Difficulty/compensating_invariant/award_allocation_identity_conserved_through_adjust_and_void
        """
        ctx, sr, ss = self._identity_setup()
        award = ctx["award"]
        household_id = ctx["household"]["id"]
        validate_success(
            api.adjust_award(award["id"], adjust_award_payload(45000, award["version"]), PM1),
            200,
        )
        mid = validate_success(api.get_benefit_summary(household_id, PM1), 200)
        assert mid["ytd_exposure_cents"] == 45000
        validate_success(api.void_award(award["id"], PM1), 200)
        summary = validate_success(api.get_benefit_summary(household_id, PM1), 200)
        assert summary["ytd_exposure_cents"] == 0, (
            "a VOIDED award drops out of the exposure set entirely"
        )
        for a in list_award_allocations(award["id"]):
            assert a["status"] == "RELEASED"


class TestAwardVoidCascade:
    def _void_setup(self):
        """Award 50000 reserved 20000 on G (drained to EXHAUSTED) + 30000 on H."""
        ctx = setup_approved(
            requested_amount_cents=50000,
            policy_overrides={"rent_cap_cents": 60000},
            sources=[
                dict(name="G", funder_name="Funder G", source_type="GRANT_RESTRICTED",
                     allowed_categories=["RENT"], total_budget_cents=20000),
                dict(name="H", funder_name="Funder H",
                     period_end="2026-12-31T00:00:00Z", total_budget_cents=40000),
            ],
        )
        sg, sh = (s["id"] for s in ctx["sources"])
        return ctx, sg, sh

    def test_void_releases_allocations_and_returns_application(self, api):
        """PRD §3.6: "A successful void flips every `RESERVED` allocation of the
        award to `RELEASED`, reduces each affected source's `reserved_cents` by
        that allocation's `allocated_cents` minus its `consumed_cents`, revives
        any `EXHAUSTED` source whose availability rises above zero back to
        `ACTIVE`, moves the application `APPROVED → PENDING_DECISION` with its
        `active_award_id` cleared to empty, and increments the award's `version`."

        Design: Difficulty/transitive_cascade/award_void_compensation_cascade
        """
        ctx, sg, sh = self._void_setup()
        award = ctx["award"]
        g_before = validate_success(api.get_funding_source(sg, PM1), 200)
        assert g_before["status"] == "EXHAUSTED"  # drained by the reservation
        voided = validate_success(api.void_award(award["id"], PM1), 200)
        assert voided["status"] == "VOIDED"
        for a in list_award_allocations(award["id"]):
            assert a["status"] == "RELEASED"
        g_after = validate_success(api.get_funding_source(sg, PM1), 200)
        assert g_after["reserved_cents"] == 0
        assert g_after["available_cents"] == 20000
        assert g_after["status"] == "ACTIVE", "EXHAUSTED source revives on release"
        h_after = validate_success(api.get_funding_source(sh, PM1), 200)
        assert h_after["reserved_cents"] == 0
        assert h_after["available_cents"] == 40000
        application = get_application(ctx["application"]["id"])
        assert application["status"] == "PENDING_DECISION"
        assert application.get("active_award_id") in (None, ""), (
            "active_award_id is cleared to empty by the void"
        )

    def test_void_reconciles_derived_household_exposure(self, api):
        """PRD §3.9: "the exposure basis counts the full `awarded_amount_cents`
        of every non-`VOIDED` award in the benefit-year set, including
        approved-but-unpaid amounts, while the committed basis counts only
        `consumed_cents` across those awards' allocations — money actually
        cleared — so the two differ whenever an award is approved but not yet
        fully paid."
        PRD §3.1: "the invariant that committed plus reserved plus available
        always equals `total_budget_cents` holds at all times."

        Design: Difficulty/transitive_cascade/award_void_compensation_cascade
        """
        ctx, sg, sh = self._void_setup()
        household_id = ctx["household"]["id"]
        before = validate_success(api.get_benefit_summary(household_id, PM1), 200)
        assert before["ytd_exposure_cents"] == 50000
        validate_success(api.void_award(ctx["award"]["id"], PM1), 200)
        after = validate_success(api.get_benefit_summary(household_id, PM1), 200)
        assert after["ytd_exposure_cents"] == 0
        for sid, budget in ((sg, 20000), (sh, 40000)):
            source = validate_success(api.get_funding_source(sid, PM1), 200)
            assert source["total_budget_cents"] == budget
            assert_source_balance_invariant(source)


class TestAwardVoidAndAdjustGuards:
    def test_award_void_with_issued_payment_rejected(self, api):
        """PRD §3.6: "Voiding unwinds an award entirely. A `ProgramManager` may
        void an award in `ACTIVE` or `PARTIALLY_DISBURSED` status — anything else
        draws `ERR_INVALID_AWARD_STATE` — subject to the same two payment guards
        in the same order: `ERR_PAYMENTS_OUTSTANDING` first when any payment is
        `ISSUED`, then `ERR_PAYMENTS_CLEARED` when any payment has `CLEARED`."

        Design: Corner/state_machines/award_void_with_issued_payment_rejected
        """
        ctx = setup_approved(requested_amount_cents=20000)
        issue_payment(
            ctx["award"]["id"], ctx["vendor"]["id"], ctx["source"]["id"], 20000
        )
        resp = api.void_award(ctx["award"]["id"], PM1)
        validate_error(resp, ApiErrorId.ERR_PAYMENTS_OUTSTANDING)
        assert get_award(ctx["award"]["id"])["status"] == "ACTIVE"
        source = validate_success(api.get_funding_source(ctx["source"]["id"], PM1), 200)
        assert source["reserved_cents"] == 20000, "a refused void changes nothing"

    def test_award_void_with_cleared_payment_rejected(self, api):
        """PRD §3.6: "Since a `PARTIALLY_DISBURSED` award by definition already
        has a cleared payment, voiding one deterministically fails with
        `ERR_PAYMENTS_CLEARED`."

        Design: Corner/state_machines/award_void_with_cleared_payment_rejected
        """
        ctx = setup_approved(requested_amount_cents=30000)
        payment = issue_payment(
            ctx["award"]["id"], ctx["vendor"]["id"], ctx["source"]["id"], 12000
        )
        clear_payment(payment["id"])
        assert get_award(ctx["award"]["id"])["status"] == "PARTIALLY_DISBURSED"
        resp = api.void_award(ctx["award"]["id"], PM1)
        validate_error(resp, ApiErrorId.ERR_PAYMENTS_CLEARED)
        assert get_award(ctx["award"]["id"])["status"] == "PARTIALLY_DISBURSED"
        source = validate_success(api.get_funding_source(ctx["source"]["id"], PM1), 200)
        assert source["committed_cents"] == 12000, "a refused void changes nothing"

    def test_adjust_voided_award_returns_invalid_award_state(self, api):
        """PRD §3.6: "The award must be in `ACTIVE` status, else
        `ERR_INVALID_AWARD_STATE`."

        Design: Corner/validations/adjust_voided_award_returns_invalid_award_state
        """
        ctx = setup_approved(requested_amount_cents=10000)
        validate_success(api.void_award(ctx["award"]["id"], PM1), 200)
        award = get_award(ctx["award"]["id"])
        assert award["status"] == "VOIDED"
        resp = api.adjust_award(
            award["id"], adjust_award_payload(5000, award["version"]), PM1
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_AWARD_STATE)

    def test_occ_award_adjust_stale_version_rejected(self, api):
        """PRD §2.7: "Adjusting an award (`POST /assistance/awards/{id}/adjust`)
        requires `expected_award_version`, holding the client-last-observed
        `version` of the award."
        PRD §2.7: "When the supplied value does not match the parent entity's
        current `version`, the write is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_award_adjust_stale_version_rejected
        """
        ctx = setup_approved(requested_amount_cents=10000)
        award = ctx["award"]
        first = validate_success(
            api.adjust_award(award["id"], adjust_award_payload(8000, award["version"]), PM1),
            200,
        )
        assert first["awarded_amount_cents"] == 8000
        resp = api.adjust_award(
            award["id"], adjust_award_payload(6000, award["version"]), PM1
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after = get_award(award["id"])
        assert after["awarded_amount_cents"] == 8000, "stale adjust changes nothing"
        assert after["version"] == first["version"]

    def test_reapproval_after_void_creates_second_award(self, api):
        """PRD §3.6: "A successful void flips every `RESERVED` allocation of the
        award to `RELEASED`, reduces each affected source's `reserved_cents` by
        that allocation's `allocated_cents` minus its `consumed_cents`, revives
        any `EXHAUSTED` source whose availability rises above zero back to
        `ACTIVE`, moves the application `APPROVED → PENDING_DECISION` with its
        `active_award_id` cleared to empty, and increments the award's `version`."
        PRD §3.5: "A successful approval creates the AssistanceAward in `ACTIVE`
        status, pins its `policy_id` to the application's pinned policy, stamps
        its `benefit_year` with the clock's current calendar year, sets its
        `awarded_amount_cents` to the determined amount, points the application's
        `active_award_id` at it, moves the application from `PENDING_DECISION`
        into `APPROVED`, and bumps the application's `version`."

        Design: Corner/state_machines/reapproval_after_void_creates_second_award
        """
        ctx = setup_approved(requested_amount_cents=10000)
        first_award_id = ctx["award"]["id"]
        app_id = ctx["application"]["id"]
        validate_success(api.void_award(first_award_id, PM1), 200)
        approved = approve_application(app_id)
        second_award_id = approved["active_award_id"]
        assert second_award_id != first_award_id, "a NEW award row, not resurrection"
        assert get_award(first_award_id)["status"] == "VOIDED"
        assert get_award(second_award_id)["status"] == "ACTIVE"
        assert approved["status"] == "APPROVED"
        awards = list_application_awards(app_id)
        assert len(awards) == 2, "award history retains the VOIDED record"
