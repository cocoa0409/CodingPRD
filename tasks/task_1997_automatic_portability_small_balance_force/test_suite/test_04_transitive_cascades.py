"""Queue A difficulty tests: transitive cascades (recordkeeper exit, check escheat)."""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    make_provider_ops_headers,
    create_active_recordkeeper,
    create_plan,
    create_participant,
    create_open_batch,
    create_case,
    send_force_out_notice_and_deliver,
    submit_election,
    setup_auto_expired_case,
)

OPS = TEST_USERS["provider_ops_headers"]
SPONSOR = TEST_USERS["plan_sponsor_headers"]


class TestRecordkeeperExitCascadeDepth3:
    def _setup(self):
        """Two IRAs from the same source batch: IRA1 MATCHED (auto-confirmed 0.910),
        IRA2 OPEN with a CANDIDATE 0.652 match — both targeting plan Y at RK-B."""
        rk_a = create_active_recordkeeper(code="RK-A", legal_name="Recordkeeper A")
        rk_b = create_active_recordkeeper(code="RK-B", legal_name="Recordkeeper B")
        plan_x = create_plan(rk_a["id"], plan_name="Plan X", sponsor_ein="11-1111111")
        plan_y = create_plan(rk_b["id"], plan_name="Plan Y", sponsor_ein="33-3333333")
        p_a = create_participant(ssn_hash="hash-a", full_name="Ann A")
        p_b = create_participant(ssn_hash="hash-b", full_name="Bob B")
        batch = create_open_batch(plan_x["id"])
        c_a = create_case(batch["id"], plan_x["id"], p_a["id"],
                          separation_date_balance_cents=300000,
                          processing_date_balance_cents=300000)
        c_b = create_case(batch["id"], plan_x["id"], p_b["id"],
                          separation_date_balance_cents=250000,
                          processing_date_balance_cents=250000)
        get_success_data(api_client.lock_distribution_batch(batch["id"], SPONSOR))
        for c, p in ((c_a, p_a), (c_b, p_b)):
            send_force_out_notice_and_deliver(c["id"])
            submit_election(c["id"], p["id"], "SAFE_HARBOR_IRA")
        get_success_data(api_client.execute_distribution_batch(
            batch["id"], make_provider_ops_headers("ops_exec_1")))
        ira1 = get_success_data(api_client.create_safe_harbor_ira(
            {"distribution_case_id": c_a["id"]}, OPS))
        ira2 = get_success_data(api_client.create_safe_harbor_ira(
            {"distribution_case_id": c_b["id"]}, OPS))
        m1 = get_success_data(api_client.create_match_search(
            ira1["id"],
            {"new_plan_id": plan_y["id"], "new_recordkeeper_id": rk_b["id"],
             "employment_start_date": "2026-08-10", "ssn_exact": True,
             "name_similarity": 0.90, "dob_match": True},
            OPS,
        ))
        m2 = get_success_data(api_client.create_match_search(
            ira2["id"],
            {"new_plan_id": plan_y["id"], "new_recordkeeper_id": rk_b["id"],
             "employment_start_date": "2026-08-10", "ssn_exact": True,
             "name_similarity": 0.34, "dob_match": False},
            OPS,
        ))
        return {"rk_a": rk_a, "rk_b": rk_b, "plan_y": plan_y,
                "ira1": ira1, "ira2": ira2, "m1": m1, "m2": m2}

    def test_exit_cascade_full_chain(self):
        """PRD §2.8: "a recordkeeper leaving the network propagates outward in a fixed
        three-link cascade. First, every plan of that recordkeeper has `network_reachable`
        recomputed to false. Second, every match candidate still in `CANDIDATE` or
        `CONFIRMED` whose new-employer plan just lost reachability transitions to
        `EXPIRED`. Third, every safe harbor IRA sitting in `MATCHED` on one of those
        just-expired confirmed matches returns to `OPEN`, with its `last_activity_at`
        deliberately left unchanged so dormancy accounting is not disturbed by an event
        the participant could not control."

        Design: Difficulty/transitive_cascade/recordkeeper_exit_cascade_depth3
        """
        ctx = self._setup()
        validate_success(api_client.exit_recordkeeper(ctx["rk_b"]["id"], OPS))

        rk_b = get_success_data(api_client.get_recordkeeper(ctx["rk_b"]["id"], OPS))
        assert rk_b["network_status"] == "EXITED"
        assert rk_b["exited_at"] is not None

        plan_y = get_success_data(api_client.get_plan(ctx["plan_y"]["id"], OPS))
        assert plan_y["network_reachable"] is False

        m1 = get_success_data(api_client.get_match_candidate(ctx["m1"]["id"], OPS))
        m2 = get_success_data(api_client.get_match_candidate(ctx["m2"]["id"], OPS))
        assert m1["match_status"] == "EXPIRED"
        assert m2["match_status"] == "EXPIRED"

        ira1 = get_success_data(api_client.get_safe_harbor_ira(ctx["ira1"]["id"], OPS))
        ira2 = get_success_data(api_client.get_safe_harbor_ira(ctx["ira2"]["id"], OPS))
        assert ira1["ira_status"] == "OPEN"
        assert ira2["ira_status"] == "OPEN"

    def test_exit_cascade_link_order_plan_before_match(self):
        """PRD §2.8: "First, every plan of that recordkeeper has `network_reachable`
        recomputed to false. Second, every match candidate still in `CANDIDATE` or
        `CONFIRMED` whose new-employer plan just lost reachability transitions to
        `EXPIRED`."

        Design: Difficulty/transitive_cascade/recordkeeper_exit_cascade_depth3
        """
        ctx = self._setup()
        validate_success(api_client.exit_recordkeeper(ctx["rk_b"]["id"], OPS))
        plan_y = get_success_data(api_client.get_plan(ctx["plan_y"]["id"], OPS))
        assert plan_y["network_reachable"] is False
        # Only the matches bound to the exited recordkeeper's plan expire.
        m1 = get_success_data(api_client.get_match_candidate(ctx["m1"]["id"], OPS))
        m2 = get_success_data(api_client.get_match_candidate(ctx["m2"]["id"], OPS))
        assert m1["match_status"] == "EXPIRED"
        assert m2["match_status"] == "EXPIRED"


class TestCheckEscheatCascadeDepth3:
    def _setup(self):
        """Auto cash-out case: check ISSUED, swept STALE_DATED at 2027-02-28,
        ESCHEAT_WARNING delivered then matured >= 90 days (clock 2027-05-30)."""
        ctx = setup_auto_expired_case(balance=100000)
        chk = get_success_data(api_client.create_check(
            {"distribution_case_id": ctx["case"]["id"]}, OPS))
        get_success_data(api_client.set_clock("2027-02-28T00:00:00Z", OPS))
        get_success_data(api_client.run_sweep(OPS))
        warn = get_success_data(api_client.create_notice(
            ctx["case"]["id"], {"notice_type": "ESCHEAT_WARNING"}, OPS))
        get_success_data(api_client.record_notice_delivery(
            warn["id"], {"outcome": "DELIVERED"}, OPS))
        get_success_data(api_client.set_clock("2027-05-30T00:00:00Z", OPS))
        ctx["check"] = get_success_data(api_client.get_check(chk["id"], OPS))
        return ctx

    def test_escheat_void_full_cascade(self):
        """PRD §3.8: "An escheatment void of a `CASE_CASH_OUT` check cascades in three
        links: the check goes `VOIDED`; the case moves from `EXECUTED` to `ESCHEATED`;
        and the batch's `settled_case_count` and `total_forced_out_cents` are recomputed,
        which can flip the batch's reconciliation eligibility (§3.9)."
        PRD §3.9: "if every attached case has reached a terminal status — `SETTLED`,
        `ESCHEATED`, or `CANCELLED` — the batch moves to `RECONCILED` and stamps
        `reconciled_at`"

        Design: Difficulty/transitive_cascade/check_escheat_cascade_depth3
        """
        ctx = self._setup()
        chk = validate_success(api_client.void_check(
            ctx["check"]["id"], {"void_reason": "ESCHEATMENT"}, OPS))
        assert chk["check_status"] == "VOIDED"
        assert chk["void_reason"] == "ESCHEATMENT"

        case = get_success_data(
            api_client.get_distribution_case(ctx["case"]["id"], OPS))
        assert case["case_status"] == "ESCHEATED"

        batch = get_success_data(
            api_client.get_distribution_batch(ctx["batch"]["id"], OPS))
        assert batch["settled_case_count"] == 1
        assert batch["case_count"] == 1

        batch = validate_success(api_client.reconcile_distribution_batch(
            ctx["batch"]["id"], OPS))
        assert batch["batch_status"] == "RECONCILED"

    def test_escheat_void_case_and_batch_counters(self):
        """PRD §3.8: "the case moves from `EXECUTED` to `ESCHEATED`; and the batch's
        `settled_case_count` and `total_forced_out_cents` are recomputed"

        Design: Difficulty/transitive_cascade/check_escheat_cascade_depth3
        """
        ctx = self._setup()
        validate_success(api_client.void_check(
            ctx["check"]["id"], {"void_reason": "ESCHEATMENT"}, OPS))
        case = get_success_data(
            api_client.get_distribution_case(ctx["case"]["id"], OPS))
        assert case["case_status"] == "ESCHEATED"
        batch = get_success_data(
            api_client.get_distribution_batch(ctx["batch"]["id"], OPS))
        assert batch["settled_case_count"] == batch["case_count"]
