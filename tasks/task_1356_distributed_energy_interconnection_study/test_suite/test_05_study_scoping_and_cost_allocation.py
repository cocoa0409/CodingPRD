"""Study scoping gates, readiness enforcement, and PROVISIONAL/FINAL cost shares."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_cost_share,
    assert_cost_shares_conserved,
    create_queued_project,
    create_ready_project,
    find_ledger_entry,
    get_cluster_group,
    get_project,
    get_study,
    list_deposit_ledger,
    list_project_cost_shares,
    publish_results,
    scope_study,
    set_clock,
    setup_developer_and_cluster,
    setup_study_scenario,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["queue_admin_headers"]
ENGINEER = TEST_USERS["study_engineer_headers"]


class TestProvisionalVsFinal:
    def test_provisional_shares_at_scoping(self, api):
        """PRD §3.4: "For each project entering `IN_STUDY`, a `CostShare` row is
        created under the **PROVISIONAL** basis — each row carries the `study_id`
        of the study and the `project_id` of the member bearing the share: each
        included member's `allocated_cents` is the study's total cost multiplied by
        the member's `capacity_mw` and divided by the sum of `capacity_mw` across
        the included set, rounded half-up to integer cents."
        PRD §3.4: "The two variants genuinely differ: for a total of 1000000 cents
        over members of ten and thirty MW, PROVISIONAL allocates 250000 and 750000
        cents, while FINAL allocates 375000 and 625000 cents."

        Design: Difficulty/dual_variant_calc/study_cost_allocation_provisional_vs_final
        """
        scenario = setup_study_scenario(
            [{"capacity_mw": 10, "technology": "SOLAR"},
             {"capacity_mw": 30, "technology": "WIND"}],
            total_cost_cents=1000000)
        p1, p2 = scenario["projects"]

        shares1 = list_project_cost_shares(p1["id"])
        shares2 = list_project_cost_shares(p2["id"])
        assert len(shares1) == 1 and len(shares2) == 1
        assert_cost_share(shares1[0])
        assert shares1[0]["allocated_cents"] == 250000, "PROVISIONAL pro-rata 10/40"
        assert shares1[0]["basis"] == "PROVISIONAL"
        assert shares2[0]["allocated_cents"] == 750000, "PROVISIONAL pro-rata 30/40"
        assert_cost_shares_conserved(shares1 + shares2, 1000000)

    def test_final_shares_after_publish(self, api):
        """PRD §3.4: "The two variants genuinely differ: for a total of 1000000
        cents over members of ten and thirty MW, PROVISIONAL allocates 250000 and
        750000 cents, while FINAL allocates 375000 and 625000 cents."
        PRD §3.5: "Publication moves the study from `IN_PROGRESS` to
        `RESULTS_PUBLISHED`, advances every included member in `IN_STUDY` to
        `STUDY_COMPLETE`, advances every included member in `RESTUDY_REQUIRED` back
        to `STUDY_COMPLETE`, and recomputes all cost shares under the FINAL basis,
        flipping each row's `basis` to `FINAL`."

        Design: Difficulty/dual_variant_calc/study_cost_allocation_provisional_vs_final
        """
        scenario = setup_study_scenario(
            [{"capacity_mw": 10, "technology": "SOLAR"},
             {"capacity_mw": 30, "technology": "WIND"}],
            total_cost_cents=1000000)
        p1, p2 = scenario["projects"]
        study = scenario["study"]
        provisional_p1 = list_project_cost_shares(p1["id"])[0]["allocated_cents"]

        publish_results(study["id"])

        shares1 = list_project_cost_shares(p1["id"])
        shares2 = list_project_cost_shares(p2["id"])
        final_p1 = shares1[0]["allocated_cents"]
        assert final_p1 == 375000, "FINAL: head 250000 + capacity 125000"
        assert shares1[0]["basis"] == "FINAL"
        assert shares2[0]["allocated_cents"] == 625000, "FINAL: head 250000 + capacity 375000"
        assert shares2[0]["basis"] == "FINAL"
        assert final_p1 != provisional_p1, (
            "identical membership and total, different variant, different cents"
        )
        assert_cost_shares_conserved(shares1 + shares2, 1000000)


class TestFinalRoundingOrder:
    def test_final_allocation_per_component_rounding(self, api):
        """PRD §3.4: "Under the FINAL basis — used at results publication and at
        every later recomputation — each included member's share is the sum of two
        components: an equal headcount component of half the total cost divided by
        the number of included members, and a capacity component of half the total
        cost multiplied by the member's `capacity_mw` and divided by the total
        included capacity. Each component is rounded half-up to integer cents
        first, and the two rounded components are then summed."
        PRD §2.5: "Where a calculation has multiple additive components, each
        component is rounded half-up to integer cents first and only then summed —
        the order is pinned and must not be reversed."

        Design: Difficulty/combinatorial_formula/study_final_allocation_per_component_rounding
        """
        scenario = setup_study_scenario(
            [{"capacity_mw": 10, "technology": "SOLAR"},
             {"capacity_mw": 10, "technology": "WIND"},
             {"capacity_mw": 20, "technology": "SOLAR"}],
            total_cost_cents=999999, publish=True)
        p1, p2, p3 = scenario["projects"]

        s1 = list_project_cost_shares(p1["id"])[0]["allocated_cents"]
        s2 = list_project_cost_shares(p2["id"])[0]["allocated_cents"]
        s3 = list_project_cost_shares(p3["id"])[0]["allocated_cents"]
        # Per-component: head round_half_up(499999.5/3)=166667 each;
        # capacity 125000 / 125000 / 250000.
        assert s1 == 291667, f"head 166667 + capacity 125000, got {s1}"
        assert s2 == 291667
        # P3's rounded components sum to 416667; residual -2 lands on the
        # largest-capacity member, giving 416665.
        assert s3 == 416665, f"416667 minus residual 2, got {s3}"

    def test_final_allocation_sum_conserved(self, api):
        """PRD §3.4: "After either variant runs, a residual reconciliation restores
        the invariant that all shares sum exactly to the study total: the
        difference between the total and the summed shares is added to the included
        project with the largest `capacity_mw`, with ties broken by earliest
        `created_at`."

        Design: Difficulty/combinatorial_formula/study_final_allocation_per_component_rounding
        """
        scenario = setup_study_scenario(
            [{"capacity_mw": 10, "technology": "SOLAR"},
             {"capacity_mw": 10, "technology": "WIND"},
             {"capacity_mw": 20, "technology": "SOLAR"}],
            total_cost_cents=999999, publish=True)
        p1, p2, p3 = scenario["projects"]
        study = scenario["study"]

        shares = (list_project_cost_shares(p1["id"]) +
                  list_project_cost_shares(p2["id"]) +
                  list_project_cost_shares(p3["id"]))
        assert_cost_shares_conserved(shares, 999999)
        assert all(s["basis"] == "FINAL" for s in shares)
        assert all(s["study_id"] == study["id"] for s in shares)


class TestProvisionalResidual:
    def test_provisional_residual_to_largest_capacity(self, api):
        """PRD §3.4: "After either variant runs, a residual reconciliation restores
        the invariant that all shares sum exactly to the study total: the
        difference between the total and the summed shares is added to the included
        project with the largest `capacity_mw`, with ties broken by earliest
        `created_at`."

        Design: Corner/calculations/provisional_allocation_residual_to_largest_capacity
        """
        scenario = setup_study_scenario(
            [{"capacity_mw": 10, "technology": "SOLAR"},
             {"capacity_mw": 10, "technology": "WIND"},
             {"capacity_mw": 20, "technology": "SOLAR"}],
            total_cost_cents=999999)
        p1, p2, p3 = scenario["projects"]

        s1 = list_project_cost_shares(p1["id"])[0]
        s2 = list_project_cost_shares(p2["id"])[0]
        s3 = list_project_cost_shares(p3["id"])[0]
        assert s1["basis"] == "PROVISIONAL"
        # round_half_up(999999 * 10/40) = 250000 each; 20 MW member rounds to
        # 500000 and absorbs the -1 residual as the largest capacity.
        assert s1["allocated_cents"] == 250000
        assert s2["allocated_cents"] == 250000
        assert s3["allocated_cents"] == 499999
        assert s1["allocated_cents"] + s2["allocated_cents"] + s3["allocated_cents"] == 999999

    def test_provisional_residual_tiebreak_earliest_created_at(self, api):
        """PRD §3.4: "the difference between the total and the summed shares is
        added to the included project with the largest `capacity_mw`, with ties
        broken by earliest `created_at`."

        Design: Corner/calculations/provisional_residual_tiebreak_earliest_created_at
        """
        developer, cluster = setup_developer_and_cluster()
        # Advance the logical clock between creations so created_at ordering is
        # defined even if created_at is stamped from the logical clock.
        set_clock("2026-08-01T00:00:00Z")
        p1 = create_ready_project(developer["id"], cluster["id"], project_name="P1",
                                  capacity_mw=10, point_of_interconnection="SUB-1",
                                  evidence_prefix="s3://ev/p1")
        set_clock("2026-08-02T00:00:00Z")
        p2 = create_ready_project(developer["id"], cluster["id"], project_name="P2",
                                  capacity_mw=10, point_of_interconnection="SUB-2",
                                  evidence_prefix="s3://ev/p2")
        assert p1["created_at"] <= p2["created_at"], "setup: P1 created before P2"

        study = scope_study(cluster["id"], total_cost_cents=999999)
        # Each raw share is round_half_up(999999/2) = 500000; residual is -1 and
        # the capacity tie is broken by earliest created_at — P1.
        s1 = list_project_cost_shares(p1["id"])[0]["allocated_cents"]
        s2 = list_project_cost_shares(p2["id"])[0]["allocated_cents"]
        assert s1 == 499999, f"earliest-created tied member absorbs residual, got {s1}"
        assert s2 == 500000
        assert s1 + s2 == 999999
        assert get_study(study["id"])["status"] == "IN_PROGRESS"


class TestScopingGates:
    def test_study_already_exists_rejected(self, api):
        """PRD §3.4: "no study may yet exist for the cluster — at most one `Study`
        ever exists per `ClusterGroup`, and a second attempt draws
        `ERR_STUDY_ALREADY_EXISTS`"
        PRD §3.4: "Scoping enforces three gates in the cluster's context: the
        cluster must still be `FORMING` (otherwise
        `ERR_CLUSTER_NOT_ACCEPTING_PROJECTS`), no study may yet exist for the
        cluster ..."
        PRD §2.8: "Sixth, state preconditions of the target resource are
        evaluated ... Ninth, structural business constraints are enforced
        (capacity, window-overlap, uniqueness, and conflict errors ...). Where
        two rules from different categories could both fire on the same request,
        the earlier category's error wins."

        A successful first scoping moves the cluster FORMING -> STUDY_UNDERWAY
        (§3.4), and no transition returns it to FORMING, so on any second
        attempt the FORMING state gate and the uniqueness gate are both armed.
        §2.8's category priority hands the win to the state gate, while §3.4
        names ERR_STUDY_ALREADY_EXISTS for "a second attempt"; the PRD names
        both members without a self-consistent unique choice, so either is
        accepted. What is uniquely determined: the attempt is rejected with a
        409 and no second study is persisted.

        Design: Corner/validations/study_already_exists_rejected
        """
        scenario = setup_study_scenario([{"capacity_mw": 10}])
        cluster = scenario["cluster"]
        study = scenario["study"]

        resp = api.create_study(cluster["id"], {"total_cost_cents": 500000}, ENGINEER)
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_STUDY_ALREADY_EXISTS,
            ApiErrorId.ERR_CLUSTER_NOT_ACCEPTING_PROJECTS,
        ])

        studies = validate_success(api.list_cluster_studies(cluster["id"], ADMIN),
                                   expected_status=200)
        assert isinstance(studies, list) and len(studies) == 1
        assert studies[0]["id"] == study["id"]

    def test_study_scope_requires_ready_project(self, api):
        """PRD §3.4: "at least one member must be `READY`, else
        `ERR_NO_READY_PROJECTS`."

        Design: Corner/validations/study_scope_requires_ready_project
        """
        developer, cluster = setup_developer_and_cluster()
        project = create_queued_project(developer["id"], cluster["id"])

        resp = api.create_study(cluster["id"], {"total_cost_cents": 1000000}, ENGINEER)
        validate_error(resp, ApiErrorId.ERR_NO_READY_PROJECTS)

        assert get_cluster_group(cluster["id"])["status"] == "FORMING"
        assert get_project(project["id"])["status"] == "QUEUED", (
            "no auto-withdrawal fired on a failed scoping"
        )

    def test_readiness_enforcement_auto_withdrawal_at_scoping(self, api):
        """PRD §3.4: "The study is created in `IN_PROGRESS`; the cluster advances
        from `FORMING` to `STUDY_UNDERWAY`; every member in `READY` moves to
        `IN_STUDY`; and every member still in `SUBMITTED` or `QUEUED` is
        automatically withdrawn for lack of readiness. That automatic withdrawal
        follows the early forfeiture band described in §3.7, and — because the
        study has only just been created — it triggers no restudy cascade."

        Design: Corner/state_machines/readiness_enforcement_auto_withdrawal_at_scoping
        """
        developer, cluster = setup_developer_and_cluster()
        p1 = create_ready_project(developer["id"], cluster["id"], project_name="P1",
                                  capacity_mw=10, point_of_interconnection="SUB-1",
                                  evidence_prefix="s3://ev/p1")
        p2 = create_queued_project(developer["id"], cluster["id"], project_name="P2",
                                   capacity_mw=20, point_of_interconnection="SUB-2")
        assert get_cluster_group(cluster["id"])["committed_mw"] == 30

        study = scope_study(cluster["id"], total_cost_cents=1000000)

        assert get_project(p1["id"])["status"] == "IN_STUDY"
        p2_after = get_project(p2["id"])
        assert p2_after["status"] == "WITHDRAWN"
        assert p2_after["deposit_posted_cents"] == 0
        ledger = list_deposit_ledger(p2["id"])
        find_ledger_entry(ledger, "DEPOSIT", 2000000)
        find_ledger_entry(ledger, "FORFEIT", 200000)   # 10% early band
        find_ledger_entry(ledger, "REFUND", 1800000)

        cluster_after = get_cluster_group(cluster["id"])
        assert cluster_after["committed_mw"] == 10, "30 - 20 withdrawn"
        assert cluster_after["status"] == "STUDY_UNDERWAY"
        assert study["status"] == "IN_PROGRESS"

        shares = list_project_cost_shares(p1["id"])
        assert len(shares) == 1
        assert shares[0]["allocated_cents"] == 1000000, (
            "sole included member bears the full PROVISIONAL share"
        )
        assert shares[0]["basis"] == "PROVISIONAL"


class TestStudyStateMachine:
    def test_study_finalize_from_in_progress_rejected(self, api):
        """PRD §3.5: "The `StudyEngineer` finalizes a study that is in
        `RESULTS_PUBLISHED` — again, any other state draws `ERR_STUDY_INVALID_STATE`"

        Design: Corner/state_machines/study_finalize_from_in_progress_rejected
        """
        scenario = setup_study_scenario([{"capacity_mw": 10}])
        study = scenario["study"]
        assert study["status"] == "IN_PROGRESS"

        resp = api.finalize_study(study["id"], ENGINEER)
        validate_error(resp, ApiErrorId.ERR_STUDY_INVALID_STATE)
        assert get_study(study["id"])["status"] == "IN_PROGRESS"

    def test_study_publish_after_finalize_rejected(self, api):
        """PRD §3.5: "Publication requires the study to be `IN_PROGRESS`; acting on
        a study in any other state is rejected with `ERR_STUDY_INVALID_STATE`."

        Design: Corner/state_machines/study_publish_after_finalize_rejected
        """
        scenario = setup_study_scenario([{"capacity_mw": 10}], publish=True,
                                        finalize=True)
        study = scenario["study"]
        assert study["status"] == "FINALIZED"

        resp = api.publish_study_results(study["id"], ENGINEER)
        validate_error(resp, ApiErrorId.ERR_STUDY_INVALID_STATE)
        assert get_study(study["id"])["status"] == "FINALIZED"
