"""Budget cascades: the three-hop approve cascade across site and program,
approve/rescind budget conservation, immediate consistency, and the OVERRUN
contingency draw."""
from test_helpers import (
    ApiErrorId,
    approve_change_order_now,
    make_finance_controller_headers,
    propose_change_order,
    read_change_order,
    read_program,
    read_site,
    setup_awarded_site,
    setup_multi_sites_in_build,
    validate_success,
)


class TestApproveCascade:
    def test_co_approve_three_hop_budget_cascade(self, api):
        """PRD §3.6: "An approved order moves to `APPROVED` and rewrites the
        site's ledger: `amount_cents` leaves `proposed_co_cents` and enters
        `approved_co_cents`; `committed_cents` — always `base_contract_cents`
        plus the sum of `APPROVED` change-order amounts — is recomputed; the
        site's `version` increments; both variance ratios and the site
        `budget_posture` re-derive; the program rollup recomputes; and the
        opening forecast recomputes with its provisional-ratio slip factor
        (§3.8)."
        PRD §3.6: "The program's `contingency_free_cents` is the pool minus
        the reserve, and its `budget_posture` reads `OVERRUN` when the free
        amount is negative, else `GUARDED` when twice the reserve exceeds the
        pool, else `WITHIN_PLAN`."

        Design: Difficulty/transitive_cascade/co_approve_three_hop_budget_cascade
        """
        ctx = setup_awarded_site(pool=250_000)
        site_id = ctx["site"]["id"]
        co = propose_change_order(site_id, 600_000,
                                  description="Foundation remediation")

        resp = approve_change_order_now(co["id"], site_id,
                                        role="ProgramDirector",
                                        approver_user_id="dir-1")
        validate_success(resp)

        # Link 1: ledger mutation.
        site = read_site(site_id)
        assert site["approved_co_cents"] == 600_000
        assert site["proposed_co_cents"] == 0
        # Link 2: final ratio 600000*10000/9000000 = 666.7 -> 667 -> WATCH.
        assert site["variance_ratio_final_bp"] == 667
        assert site["budget_posture"] == "WATCH"

        # Link 3: 25% of the 600000 overrun enters the reserve; twice the
        # reserve (300000) exceeds the 250000 pool -> GUARDED.
        program = read_program(ctx["program"]["id"])
        assert program["contingency_reserved_cents"] == 150_000
        assert program["contingency_free_cents"] == 100_000
        assert program["budget_posture"] == "GUARDED"

    def test_two_watch_sites_push_program_overrun(self, api):
        """PRD §3.6: "the reserve charges one quarter of that overrun for
        `WATCH` sites and the whole overrun for `OVERRUN` sites, each term
        rounded half up to whole cents before summation into
        `contingency_reserved_cents`. The program's `contingency_free_cents`
        is the pool minus the reserve, and its `budget_posture` reads
        `OVERRUN` when the free amount is negative, else `GUARDED` when twice
        the reserve exceeds the pool, else `WITHIN_PLAN`."

        Design: Difficulty/transitive_cascade/co_approve_three_hop_budget_cascade
        """
        ctx = setup_multi_sites_in_build(site_count=2, crews=2, pool=250_000)
        for site in ctx["sites"]:
            co = propose_change_order(site["id"], 600_000,
                                      description="Foundation remediation")
            resp = approve_change_order_now(co["id"], site["id"],
                                            role="ProgramDirector",
                                            approver_user_id="dir-1")
            validate_success(resp)
            assert read_site(site["id"])["budget_posture"] == "WATCH"

        # Two 25% terms of 150000 each: reserve 300000 against a 250000 pool.
        program = read_program(ctx["program"]["id"])
        assert program["contingency_reserved_cents"] == 300_000
        assert program["contingency_free_cents"] == -50_000
        assert program["budget_posture"] == "OVERRUN"


class TestApproveRescindConservation:
    def test_co_approve_rescind_budget_conservation(self, api):
        """PRD §3.6: "Rescission by a `FinanceController`, accompanied by a
        `rescind_reason`, moves an `APPROVED` order to `RESCINDED` as the
        exact compensation of approval: the site must not be `OPEN` or
        `REMOVED` (`ERR_INVALID_STATE`), the amount leaves `approved_co_cents`,
        `committed_cents` recomputes, the site's `version` increments, and
        variance ratios, postures, the program rollup, and the opening
        forecast all re-derive."

        Design: Difficulty/compensating_invariant/co_approve_rescind_budget_conservation
        """
        ctx = setup_awarded_site(pool=250_000)
        site_id = ctx["site"]["id"]
        program_before = read_program(ctx["program"]["id"])
        assert program_before["committed_cents"] == 9_000_000
        assert program_before["contingency_reserved_cents"] == 0

        co = propose_change_order(site_id, 600_000,
                                  description="Foundation remediation")
        resp = approve_change_order_now(co["id"], site_id,
                                        role="ProgramDirector",
                                        approver_user_id="dir-1")
        validate_success(resp)
        # Sanity: approve moved the aggregates.
        assert read_program(ctx["program"]["id"])["contingency_reserved_cents"] == 150_000

        resp = api.rescind_change_order(
            co["id"], {"rescind_reason": "scope reverted to prototype"},
            headers=make_finance_controller_headers("fin-1"))
        assert validate_success(resp)["status"] == "RESCINDED"

        # The pair conserves money exactly: no drift on any aggregate.
        program = read_program(ctx["program"]["id"])
        assert program["committed_cents"] == 9_000_000
        assert program["contingency_reserved_cents"] == 0
        assert program["budget_posture"] == "WITHIN_PLAN"
        assert read_site(site_id)["approved_co_cents"] == 0

    def test_rescind_one_of_two_approvals_leaves_the_other(self, api):
        """PRD §3.6: "`committed_cents` — always `base_contract_cents` plus
        the sum of `APPROVED` change-order amounts — is recomputed"
        PRD §3.6: "moves an `APPROVED` order to `RESCINDED` as the exact
        compensation of approval"

        Design: Difficulty/compensating_invariant/co_approve_rescind_budget_conservation
        """
        ctx = setup_awarded_site(pool=250_000)
        site_id = ctx["site"]["id"]
        co1 = propose_change_order(site_id, 400_000, description="Millwork add")
        co2 = propose_change_order(site_id, 200_000, description="Lighting add")
        for co in (co1, co2):
            resp = approve_change_order_now(co["id"], site_id,
                                            role="FinanceController",
                                            approver_user_id="fin-1")
            validate_success(resp)
        assert read_site(site_id)["committed_cents"] == 9_600_000

        resp = api.rescind_change_order(
            co1["id"], {"rescind_reason": "scope reverted to prototype"},
            headers=make_finance_controller_headers("fin-1"))
        validate_success(resp)

        # Only the rescinded amount leaves the ledger; co2's contribution
        # remains conserved.
        site = read_site(site_id)
        assert site["approved_co_cents"] == 200_000
        assert site["committed_cents"] == 9_200_000
        assert read_change_order(co1["id"])["status"] == "RESCINDED"
        assert read_change_order(co2["id"])["status"] == "APPROVED"
        assert read_program(ctx["program"]["id"])["committed_cents"] == 9_200_000


class TestImmediateConsistency:
    def test_immediate_consistency_after_co_approve(self, api):
        """PRD §2.8: "Whenever an underlying fact changes, the server
        reconciles every dependent aggregate immediately, within the same
        request, so clients never observe a stale derived value."

        Design: Corner/consistency_model/c_immediate_consistency_after_co_approve
        """
        ctx = setup_awarded_site()
        site_id = ctx["site"]["id"]
        co = propose_change_order(site_id, 400_000, description="Added millwork")

        resp = approve_change_order_now(co["id"], site_id,
                                        role="FinanceController",
                                        approver_user_id="fin-1")
        assert validate_success(resp)["status"] == "APPROVED"

        # The very next reads already reflect the ledger and the rollup.
        site = read_site(site_id)
        assert site["approved_co_cents"] == 400_000
        assert site["proposed_co_cents"] == 0
        assert site["committed_cents"] == 9_400_000
        assert read_program(ctx["program"]["id"])["committed_cents"] == 9_400_000


class TestContingencyReserve:
    def test_contingency_reserve_overrun_full_draw(self, api):
        """PRD §3.6: "The contingency reserve works per site: a site's overrun
        is its `committed_cents` minus its `base_contract_cents`, floored at
        zero; the reserve charges one quarter of that overrun for `WATCH`
        sites and the whole overrun for `OVERRUN` sites, each term rounded
        half up to whole cents before summation into
        `contingency_reserved_cents`."
        PRD §3.6: "The site's `budget_posture` keys off the final ratio: at
        most 500 basis points reads `WITHIN`, at most 1500 reads `WATCH`, and
        beyond that `OVERRUN`."

        Design: Corner/calculations/c_contingency_reserve_overrun_full_draw
        """
        ctx = setup_awarded_site(pool=5_000_000, bid_amount_cents=9_000_000,
                                 budget_allocation_cents=12_000_000)
        site_id = ctx["site"]["id"]
        co = propose_change_order(site_id, 1_500_000,
                                  cost_category="CODE_COMPLIANCE",
                                  description="Full sprinkler retrofit")

        resp = approve_change_order_now(co["id"], site_id,
                                        role="ProgramDirector",
                                        approver_user_id="dir-1")
        validate_success(resp)

        # Final ratio 1500000*10000/9000000 = 1666.7 -> 1667 -> OVERRUN.
        site = read_site(site_id)
        assert site["variance_ratio_final_bp"] == 1667
        assert site["budget_posture"] == "OVERRUN"

        # An OVERRUN site draws its whole 1500000 overrun into the reserve;
        # twice the reserve (3000000) does not exceed the 5000000 pool.
        program = read_program(ctx["program"]["id"])
        assert program["contingency_reserved_cents"] == 1_500_000
        assert program["contingency_free_cents"] == 3_500_000
        assert program["budget_posture"] == "WITHIN_PLAN"
