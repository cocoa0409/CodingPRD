"""Withdrawal: forfeiture bands, queue compaction, committed_mw conservation, and
the restudy cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_cost_shares_conserved,
    create_project,
    create_queued_project,
    find_ledger_entry,
    get_cluster_group,
    get_project,
    get_study,
    list_deposit_ledger,
    list_project_cost_shares,
    make_developer_headers,
    publish_results,
    setup_developer_and_cluster,
    setup_project_agreement_pending,
    setup_study_scenario,
    validate_error,
    validate_paginated,
    withdraw_project,
)

ADMIN = TEST_USERS["queue_admin_headers"]


class TestForfeitureBands:
    def test_forfeiture_study_band_50pct(self, api):
        """PRD §3.7: "from `IN_STUDY`, `STUDY_COMPLETE`, or `RESTUDY_REQUIRED` it
        forfeits fifty percent"
        PRD §3.7: "When `deposit_posted_cents` is greater than zero, the system
        appends a `FORFEIT` ledger entry for the forfeited amount and — only when
        the refund portion is itself greater than zero — a `REFUND` entry for the
        remainder; either way `deposit_posted_cents` falls to zero, and each new
        entry's `balance_after_cents` records the running balance as usual."

        Design: Corner/calculations/forfeiture_study_band_50pct
        """
        scenario = setup_study_scenario([{"capacity_mw": 10}], total_cost_cents=1000000)
        project = scenario["projects"][0]
        developer = scenario["developer"]
        assert project["status"] == "IN_STUDY"

        withdraw_project(project["id"], acting_developer_id=developer["id"])

        ledger = list_deposit_ledger(project["id"])
        assert len(ledger) == 3
        assert find_ledger_entry(ledger, "DEPOSIT", 1000000)["balance_after_cents"] == 1000000
        assert find_ledger_entry(ledger, "FORFEIT", 500000)["balance_after_cents"] == 500000
        assert find_ledger_entry(ledger, "REFUND", 500000)["balance_after_cents"] == 0

        after = get_project(project["id"])
        assert after["deposit_posted_cents"] == 0
        assert after["status"] == "WITHDRAWN"

    def test_forfeiture_agreement_band_100pct(self, api):
        """PRD §3.7: "from `AGREEMENT_PENDING` or `AGREEMENT_EXECUTED` it forfeits
        one hundred percent."
        PRD §3.7: "only when the refund portion is itself greater than zero — a
        `REFUND` entry for the remainder"
        PRD §3.7: "Any `ISSUED` agreement belonging to the withdrawing project
        transitions to `EXPIRED`."

        Design: Corner/calculations/forfeiture_agreement_band_100pct
        """
        scenario = setup_project_agreement_pending(finalize=True)
        project = scenario["project"]
        developer = scenario["developer"]
        agreement = scenario["agreement"]
        assert project["status"] == "AGREEMENT_PENDING"

        withdraw_project(project["id"], acting_developer_id=developer["id"])

        ledger = list_deposit_ledger(project["id"])
        assert len(ledger) == 2, "100% band leaves no refund portion"
        assert find_ledger_entry(ledger, "DEPOSIT", 1000000)
        assert find_ledger_entry(ledger, "FORFEIT", 1000000)["balance_after_cents"] == 0
        assert all(e["tx_type"] != "REFUND" for e in ledger), "no REFUND row at 100%"

        after = get_project(project["id"])
        assert after["deposit_posted_cents"] == 0
        assert after["status"] == "WITHDRAWN"

        agreements, _meta = validate_paginated(
            api.list_project_agreements(project["id"], ADMIN))
        assert agreements[0]["id"] == agreement["id"]
        assert agreements[0]["status"] == "EXPIRED"


class TestWithdrawalIdempotencyAndCompaction:
    def test_double_withdraw_rejected(self, api):
        """PRD §3.7: "Withdrawal from `COMMERCIAL_OPERATION` or from `WITHDRAWN`
        itself is not permitted; the attempt is rejected with
        `ERR_PROJECT_NOT_WITHDRAWABLE` (HTTP 409)."

        Design: Corner/state_machines/double_withdraw_rejected
        """
        developer, cluster = setup_developer_and_cluster()
        project = create_queued_project(developer["id"], cluster["id"])
        withdraw_project(project["id"], acting_developer_id=developer["id"])

        resp = api.withdraw_project(project["id"],
                                    make_developer_headers(developer["id"]))
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_WITHDRAWABLE)

        ledger = list_deposit_ledger(project["id"])
        assert len(ledger) == 3, "the failed second withdrawal added nothing"
        find_ledger_entry(ledger, "DEPOSIT", 1000000)
        find_ledger_entry(ledger, "FORFEIT", 100000)   # 10% band from QUEUED
        find_ledger_entry(ledger, "REFUND", 900000)

    def test_queue_position_compaction_on_queued_withdrawal(self, api):
        """PRD §3.7: "Withdrawal also subtracts the project's `capacity_mw` from
        the cluster's `committed_mw` and compacts the queue: every non-withdrawn
        member of the same cluster whose `queue_position` was greater than the
        withdrawn project's position decrements by exactly one, keeping positions
        dense from one to the surviving count."

        Design: Corner/state_machines/queue_position_compaction_on_queued_withdrawal
        """
        developer, cluster = setup_developer_and_cluster()
        p1 = create_queued_project(developer["id"], cluster["id"], project_name="P1",
                                   point_of_interconnection="SUB-1")
        p2 = create_queued_project(developer["id"], cluster["id"], project_name="P2",
                                   point_of_interconnection="SUB-2")
        p3 = create_queued_project(developer["id"], cluster["id"], project_name="P3",
                                   point_of_interconnection="SUB-3")
        assert (get_project(p1["id"])["queue_position"],
                get_project(p2["id"])["queue_position"],
                get_project(p3["id"])["queue_position"]) == (1, 2, 3)

        withdraw_project(p2["id"], acting_developer_id=developer["id"])

        assert get_project(p1["id"])["queue_position"] == 1, "position 1 unchanged"
        p3_after = get_project(p3["id"])
        assert p3_after["queue_position"] == 2, "position 3 compacts to 2"
        assert get_project(p2["id"])["status"] == "WITHDRAWN"

        ledger = list_deposit_ledger(p2["id"])
        find_ledger_entry(ledger, "FORFEIT", 100000)
        find_ledger_entry(ledger, "REFUND", 900000)


class TestCommittedMwConservation:
    def test_committed_mw_rises_on_creation(self, api):
        """PRD §3.1: "The `committed_mw` figure is read-only and is reconciled
        incrementally: it rises by a project's `capacity_mw` whenever a project is
        created into the cluster, and falls by the same amount whenever a member
        withdraws"

        Design: Difficulty/compensating_invariant/committed_mw_create_withdraw_conservation
        """
        developer, cluster = setup_developer_and_cluster()
        assert get_cluster_group(cluster["id"])["committed_mw"] == 0

        create_project(developer["id"], cluster["id"], project_name="P1",
                       capacity_mw=10, point_of_interconnection="SUB-1")
        assert get_cluster_group(cluster["id"])["committed_mw"] == 10
        create_project(developer["id"], cluster["id"], project_name="P2",
                       capacity_mw=20, point_of_interconnection="SUB-2")
        assert get_cluster_group(cluster["id"])["committed_mw"] == 30

    def test_committed_mw_restored_after_withdrawal(self, api):
        """PRD §3.1: "so creating and then withdrawing the same project leaves
        `committed_mw` exactly unchanged, and at any moment it equals the sum of
        `capacity_mw` over member projects whose status is anything other than
        `WITHDRAWN`."

        Design: Difficulty/compensating_invariant/committed_mw_create_withdraw_conservation
        """
        developer, cluster = setup_developer_and_cluster()
        p1 = create_project(developer["id"], cluster["id"], project_name="P1",
                            capacity_mw=10, point_of_interconnection="SUB-1")
        p2 = create_project(developer["id"], cluster["id"], project_name="P2",
                            capacity_mw=20, point_of_interconnection="SUB-2")
        assert get_cluster_group(cluster["id"])["committed_mw"] == 30

        withdraw_project(p1["id"], acting_developer_id=developer["id"])

        cluster_after = get_cluster_group(cluster["id"])
        assert cluster_after["committed_mw"] == 20, (
            "create(+10) then withdraw(-10) leaves only P2's 20"
        )
        assert get_project(p1["id"])["status"] == "WITHDRAWN"
        assert get_project(p2["id"])["queue_position"] is None, (
            "P2 never queued, so no compaction applies to it"
        )


class TestRestudyCascade:
    def _setup_three_member_published_study(self, api):
        scenario = setup_study_scenario(
            [{"capacity_mw": 10, "technology": "SOLAR"},
             {"capacity_mw": 20, "technology": "SOLAR"},
             {"capacity_mw": 30, "technology": "WIND"}],
            total_cost_cents=1200000, publish=True)
        return scenario

    def test_withdrawal_reopens_study_and_demotes_siblings(self, api):
        """PRD §3.5: "If a member withdraws while the cluster study is in
        `RESULTS_PUBLISHED`, the study automatically reopens from
        `RESULTS_PUBLISHED` back to `IN_PROGRESS`, and every sibling member sitting
        in `STUDY_COMPLETE` is demoted to `RESTUDY_REQUIRED`"

        Design: Difficulty/transitive_cascade/withdrawal_restudy_cascade_depth3
        """
        scenario = self._setup_three_member_published_study(api)
        p1, p2, p3 = scenario["projects"]
        developer = scenario["developer"]
        study = scenario["study"]
        assert study["status"] == "RESULTS_PUBLISHED"

        withdraw_project(p2["id"], acting_developer_id=developer["id"])

        # Hop 1: the withdrawal reopens the study.
        assert get_study(study["id"])["status"] == "IN_PROGRESS"
        # Hop 2: the reopen demotes the STUDY_COMPLETE siblings.
        assert get_project(p1["id"])["status"] == "RESTUDY_REQUIRED"
        assert get_project(p3["id"])["status"] == "RESTUDY_REQUIRED"

    def test_withdrawal_recomputes_shares_and_compacts_queue(self, api):
        """PRD §3.7: "A withdrawal while the study is `RESULTS_PUBLISHED`
        additionally reopens the study to `IN_PROGRESS` and demotes every sibling
        in `STUDY_COMPLETE` to `RESTUDY_REQUIRED` before the recomputation runs."
        PRD §3.4: "The included set is the member projects of the study's cluster
        whose status is one of `IN_STUDY`, `STUDY_COMPLETE`, `RESTUDY_REQUIRED`,
        `AGREEMENT_PENDING`, or `AGREEMENT_EXECUTED`; withdrawn projects are
        excluded, and any cost-share row belonging to a withdrawn project has its
        `allocated_cents` set to zero."

        Design: Difficulty/transitive_cascade/withdrawal_restudy_cascade_depth3
        """
        scenario = self._setup_three_member_published_study(api)
        p1, p2, p3 = scenario["projects"]
        developer = scenario["developer"]
        cluster = scenario["cluster"]

        withdraw_project(p2["id"], acting_developer_id=developer["id"])

        # Hop 3: FINAL recompute over the surviving included set {10, 30} MW.
        s1 = list_project_cost_shares(p1["id"])[0]["allocated_cents"]
        s2 = list_project_cost_shares(p2["id"])[0]["allocated_cents"]
        s3 = list_project_cost_shares(p3["id"])[0]["allocated_cents"]
        assert s1 == 450000, "head 300000 + capacity 150000"
        assert s3 == 750000, "head 300000 + capacity 450000"
        assert s2 == 0, "withdrawn project's row zeroed"
        assert s1 + s2 + s3 == 1200000

        assert get_cluster_group(cluster["id"])["committed_mw"] == 40, "60 - 20"
        assert get_project(p3["id"])["queue_position"] == 2, "compacted from 3"

        p2_after = get_project(p2["id"])
        assert p2_after["deposit_posted_cents"] == 0
        ledger = list_deposit_ledger(p2["id"])
        find_ledger_entry(ledger, "FORFEIT", 1000000)  # 50% band of 2000000
        find_ledger_entry(ledger, "REFUND", 1000000)


class TestRestudyCycle:
    def test_sibling_withdrawal_demotes_to_restudy_required(self, api):
        """PRD §3.5: "every sibling member sitting in `STUDY_COMPLETE` is demoted
        to `RESTUDY_REQUIRED` — remaining an included member for the next cost
        recomputation, which then reruns over the surviving included set under the
        current basis."

        Design: Difficulty/non_linear_state_machine/project_study_complete_restudy_cycle
        """
        scenario = setup_study_scenario(
            [{"capacity_mw": 10, "technology": "SOLAR"},
             {"capacity_mw": 30, "technology": "WIND"}],
            total_cost_cents=1000000, publish=True)
        p1, p2 = scenario["projects"]
        developer = scenario["developer"]
        assert get_project(p1["id"])["status"] == "STUDY_COMPLETE"

        withdraw_project(p2["id"], acting_developer_id=developer["id"])
        assert get_project(p1["id"])["status"] == "RESTUDY_REQUIRED", (
            "STUDY_COMPLETE -> RESTUDY_REQUIRED on sibling withdrawal"
        )

    def test_republish_completes_restudy_cycle(self, api):
        """PRD §3.7: "A project in `RESTUDY_REQUIRED` completes the cycle when the
        reopened study next publishes results, returning to `STUDY_COMPLETE` with
        shares again computed under the FINAL basis."
        PRD §3.5: "Publication requires the study to be `IN_PROGRESS`"

        Design: Difficulty/non_linear_state_machine/project_study_complete_restudy_cycle
        """
        scenario = setup_study_scenario(
            [{"capacity_mw": 10, "technology": "SOLAR"},
             {"capacity_mw": 30, "technology": "WIND"}],
            total_cost_cents=1000000, publish=True)
        p1, p2 = scenario["projects"]
        developer = scenario["developer"]
        study = scenario["study"]

        withdraw_project(p2["id"], acting_developer_id=developer["id"])
        assert get_study(study["id"])["status"] == "IN_PROGRESS"
        assert get_project(p1["id"])["status"] == "RESTUDY_REQUIRED"

        publish_results(study["id"])
        assert get_project(p1["id"])["status"] == "STUDY_COMPLETE", (
            "RESTUDY_REQUIRED -> STUDY_COMPLETE on republish — cycle closed"
        )
        assert get_study(study["id"])["status"] == "RESULTS_PUBLISHED"


class TestCostTotalConservation:
    def _setup(self, api):
        return setup_study_scenario(
            [{"capacity_mw": 10, "technology": "SOLAR"},
             {"capacity_mw": 20, "technology": "SOLAR"},
             {"capacity_mw": 30, "technology": "WIND"}],
            total_cost_cents=1200000, publish=True)

    def test_cost_total_conserved_across_withdrawal_reallocation(self, api):
        """PRD §3.4: "After either variant runs, a residual reconciliation restores
        the invariant that all shares sum exactly to the study total"
        PRD §3.7: "A withdrawal while the cluster study is `IN_PROGRESS` recomputes
        cost shares over the remaining included members and zeroes the withdrawn
        project's row."

        Design: Difficulty/compensating_invariant/study_cost_total_conserved_across_withdrawal_reallocation
        """
        scenario = self._setup(api)
        p1, p2, p3 = scenario["projects"]
        developer = scenario["developer"]

        before = (list_project_cost_shares(p1["id"]) +
                  list_project_cost_shares(p2["id"]) +
                  list_project_cost_shares(p3["id"]))
        assert_cost_shares_conserved(before, 1200000)

        withdraw_project(p3["id"], acting_developer_id=developer["id"])

        after = (list_project_cost_shares(p1["id"]) +
                 list_project_cost_shares(p2["id"]) +
                 list_project_cost_shares(p3["id"]))
        assert_cost_shares_conserved(after, 1200000), (
            "total cents conserved across the withdrawal + reallocation pair"
        )

    def test_withdrawn_member_share_zeroed_and_redistributed(self, api):
        """PRD §3.4: "withdrawn projects are excluded, and any cost-share row
        belonging to a withdrawn project has its `allocated_cents` set to zero."
        PRD §3.7: "A withdrawal while the cluster study is `IN_PROGRESS` recomputes
        cost shares over the remaining included members and zeroes the withdrawn
        project's row."

        Design: Difficulty/compensating_invariant/study_cost_total_conserved_across_withdrawal_reallocation
        """
        scenario = self._setup(api)
        p1, p2, p3 = scenario["projects"]
        developer = scenario["developer"]

        withdraw_project(p3["id"], acting_developer_id=developer["id"])

        # FINAL recompute over {10, 20} MW: head 300000 each; capacity
        # 200000 / 400000.
        s1 = list_project_cost_shares(p1["id"])[0]
        s2 = list_project_cost_shares(p2["id"])[0]
        s3 = list_project_cost_shares(p3["id"])[0]
        assert s1["allocated_cents"] == 500000
        assert s2["allocated_cents"] == 700000
        assert s3["allocated_cents"] == 0, "withdrawn member zeroed"
