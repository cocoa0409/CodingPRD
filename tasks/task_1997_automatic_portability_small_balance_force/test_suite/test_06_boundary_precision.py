"""Queue A difficulty tests: boundary precision (money thresholds, time, scores)."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_participant_headers,
    make_provider_ops_headers,
    create_active_recordkeeper,
    create_plan,
    create_participant,
    create_open_batch,
    create_case,
    send_force_out_notice_and_deliver,
    setup_established_ira,
    setup_second_active_recordkeeper_and_plan,
)

OPS = TEST_USERS["provider_ops_headers"]
SPONSOR = TEST_USERS["plan_sponsor_headers"]


class TestForceOutBandBoundaryAtThresholds:
    def _setup_four_cases(self):
        """One batch with four cases at exactly 100000, 100001, 700000, 700001."""
        rk = create_active_recordkeeper()
        plan = create_plan(rk["id"])
        batch = create_open_batch(plan["id"])
        participants = [
            create_participant(ssn_hash=f"hash-{c}", full_name=f"P {c}")
            for c in "abcd"
        ]
        cases = []
        for p, balance in zip(participants, (100000, 100001, 700000, 700001)):
            cases.append(create_case(
                batch["id"], plan["id"], p["id"],
                separation_date_balance_cents=balance,
                processing_date_balance_cents=balance,
            ))
        get_success_data(api_client.lock_distribution_batch(batch["id"], SPONSOR))
        return [get_success_data(api_client.get_distribution_case(c["id"], OPS))
                for c in cases]

    def test_cash_out_threshold_inclusive(self):
        """PRD §3.3: "The boundaries are inclusive exactly as stated — a balance equal to
        the cash-out threshold is a cash-out while one cent above it goes to an IRA, and a
        balance equal to the rollover threshold goes to an IRA while one cent above it
        remains in the plan."

        Design: Difficulty/boundary_precision_check/force_out_band_boundary_at_thresholds
        """
        c1, c2, c3, c4 = self._setup_four_cases()
        assert c1["vested_balance_cents"] == 100000
        assert c1["force_out_path"] == "CASH_OUT"
        assert c2["vested_balance_cents"] == 100001
        assert c2["force_out_path"] == "SAFE_HARBOR_IRA"

    def test_rollover_threshold_inclusive_and_ineligible(self):
        """PRD §3.3: "a balance equal to the rollover threshold goes to an IRA while one
        cent above it remains in the plan."
        PRD §3.3: "Cases locked into `INELIGIBLE_REMAINS` move straight from `IDENTIFIED`
        to `SETTLED` with `executed_path` `REMAIN_IN_PLAN`: no notice, no money movement."

        Design: Difficulty/boundary_precision_check/force_out_band_boundary_at_thresholds
        """
        c1, c2, c3, c4 = self._setup_four_cases()
        assert c3["vested_balance_cents"] == 700000
        assert c3["force_out_path"] == "SAFE_HARBOR_IRA"
        assert c4["vested_balance_cents"] == 700001
        assert c4["force_out_path"] == "INELIGIBLE_REMAINS"
        assert c4["case_status"] == "SETTLED"
        assert c4["executed_path"] == "REMAIN_IN_PLAN"


class TestElectionWindowInclusiveDeadline:
    def _setup_two_notified_cases(self):
        """Batch LOCKED with two cases, both FORCE_OUT_ELECTION notices DELIVERED at the
        default clock (deadline 2026-08-31T00:00:00Z)."""
        rk = create_active_recordkeeper()
        plan = create_plan(rk["id"])
        p_a = create_participant(ssn_hash="hash-a", full_name="Ann A")
        p_b = create_participant(ssn_hash="hash-b", full_name="Bob B")
        batch = create_open_batch(plan["id"])
        c_a = create_case(batch["id"], plan["id"], p_a["id"],
                          separation_date_balance_cents=50000,
                          processing_date_balance_cents=50000)
        c_b = create_case(batch["id"], plan["id"], p_b["id"],
                          separation_date_balance_cents=50000,
                          processing_date_balance_cents=50000)
        get_success_data(api_client.lock_distribution_batch(batch["id"], SPONSOR))
        send_force_out_notice_and_deliver(c_a["id"])
        send_force_out_notice_and_deliver(c_b["id"])
        return {"p_a": p_a, "p_b": p_b, "c_a": c_a, "c_b": c_b}

    def test_election_at_exact_deadline_succeeds(self):
        """PRD §3.4: "The election window is inclusive at its upper edge: elections and
        voids are accepted while the current instant is at or before the current notice's
        `response_deadline` — a submission at exactly the deadline instant succeeds, and
        one second later it fails with `ERR_ELECTION_WINDOW_CLOSED`."

        Design: Difficulty/boundary_precision_check/election_window_inclusive_deadline
        """
        ctx = self._setup_two_notified_cases()
        get_success_data(api_client.set_clock("2026-08-31T00:00:00Z", OPS))
        case = get_success_data(api_client.get_distribution_case(ctx["c_a"]["id"], OPS))
        election = validate_success(api_client.create_election(
            ctx["c_a"]["id"],
            {"election_type": "LUMP_SUM_CASH",
             "expected_case_version": case["version"]},
            make_participant_headers(ctx["p_a"]["id"]),
        ), 201)
        assert election["election_status"] == "SUBMITTED"
        case = get_success_data(api_client.get_distribution_case(ctx["c_a"]["id"], OPS))
        assert case["case_status"] == "ELECTED"

    def test_election_one_second_after_deadline_fails(self):
        """PRD §3.4: "a submission at exactly the deadline instant succeeds, and one second
        later it fails with `ERR_ELECTION_WINDOW_CLOSED`."

        Design: Difficulty/boundary_precision_check/election_window_inclusive_deadline
        """
        ctx = self._setup_two_notified_cases()
        # First, prove the deadline edge passes for case A.
        get_success_data(api_client.set_clock("2026-08-31T00:00:00Z", OPS))
        case_a = get_success_data(api_client.get_distribution_case(ctx["c_a"]["id"], OPS))
        validate_success(api_client.create_election(
            ctx["c_a"]["id"],
            {"election_type": "LUMP_SUM_CASH",
             "expected_case_version": case_a["version"]},
            make_participant_headers(ctx["p_a"]["id"]),
        ), 201)
        # One second past the deadline, no sweep: case B is still NOTIFIED and the
        # temporal rule fires.
        get_success_data(api_client.set_clock("2026-08-31T00:00:01Z", OPS))
        case_b = get_success_data(api_client.get_distribution_case(ctx["c_b"]["id"], OPS))
        res = api_client.create_election(
            ctx["c_b"]["id"],
            {"election_type": "LUMP_SUM_CASH",
             "expected_case_version": case_b["version"]},
            make_participant_headers(ctx["p_b"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_ELECTION_WINDOW_CLOSED, 422)
        case_b = get_success_data(api_client.get_distribution_case(ctx["c_b"]["id"], OPS))
        assert case_b["case_status"] == "NOTIFIED"


class TestMatchScoreAutoConfirmBoundary:
    def _setup_two_iras(self):
        """Two IRAs OPEN (same source batch, elected path); destination plan Y at RK-B."""
        rk_a = create_active_recordkeeper(code="RK-A", legal_name="Recordkeeper A")
        rk_b, plan_y = setup_second_active_recordkeeper_and_plan()
        plan_x = create_plan(rk_a["id"], plan_name="Plan X", sponsor_ein="11-1111111")
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
            from test_helpers import submit_election
            submit_election(c["id"], p["id"], "SAFE_HARBOR_IRA")
        get_success_data(api_client.execute_distribution_batch(
            batch["id"], make_provider_ops_headers("ops_exec_1")))
        ira1 = get_success_data(api_client.create_safe_harbor_ira(
            {"distribution_case_id": c_a["id"]}, OPS))
        ira2 = get_success_data(api_client.create_safe_harbor_ira(
            {"distribution_case_id": c_b["id"]}, OPS))
        return {"ira1": ira1, "ira2": ira2, "plan_y": plan_y, "rk_b": rk_b}

    def test_score_0_850_auto_confirms(self):
        """PRD §3.7: "A score of at least 0.850 confirms immediately, but only when
        `ssn_exact` is true; the same score without an exact SSN falls back to
        `CANDIDATE`, because the SSN gate caps non-SSN feeds at 0.45 and they can never
        auto-confirm. A score of exactly 0.850 with an exact SSN confirms on the spot."

        Design: Difficulty/boundary_precision_check/match_score_auto_confirm_boundary
        """
        ctx = self._setup_two_iras()
        # 0.55 + 0.30*0.50 + 0.15 = 0.850 exactly
        m1 = validate_success(api_client.create_match_search(
            ctx["ira1"]["id"],
            {"new_plan_id": ctx["plan_y"]["id"],
             "new_recordkeeper_id": ctx["rk_b"]["id"],
             "employment_start_date": "2026-08-10", "ssn_exact": True,
             "name_similarity": 0.50, "dob_match": True},
            OPS,
        ), 201)
        assert m1["match_score"] == pytest.approx(0.850, abs=1e-9)
        assert m1["match_status"] == "CONFIRMED"
        ira1 = get_success_data(api_client.get_safe_harbor_ira(ctx["ira1"]["id"], OPS))
        assert ira1["ira_status"] == "MATCHED"

    def test_score_0_847_lands_candidate_then_manual_confirm(self):
        """PRD §3.7: "A score of at least 0.400 but below 0.850 parks the candidate in
        `CANDIDATE`, the manual-review queue"
        PRD §3.7: "Manual review can confirm or reject a `CANDIDATE`. A manual confirm
        checks the SSN gate first — a candidate without an exact SSN is rejected with
        `ERR_SSN_GATE_FAILED` — and only then the score floor: a `match_score` below 0.650
        is rejected with `ERR_MATCH_SCORE_BELOW_THRESHOLD`"

        Design: Difficulty/boundary_precision_check/match_score_auto_confirm_boundary
        """
        ctx = self._setup_two_iras()
        # 0.55 + 0.30*0.49 + 0.15 = 0.847, just below the auto-confirm band.
        m2 = validate_success(api_client.create_match_search(
            ctx["ira2"]["id"],
            {"new_plan_id": ctx["plan_y"]["id"],
             "new_recordkeeper_id": ctx["rk_b"]["id"],
             "employment_start_date": "2026-08-10", "ssn_exact": True,
             "name_similarity": 0.49, "dob_match": True},
            OPS,
        ), 201)
        assert m2["match_score"] == pytest.approx(0.847, abs=1e-9)
        assert m2["match_status"] == "CANDIDATE"

        m2 = validate_success(api_client.confirm_match_candidate(m2["id"], OPS))
        assert m2["match_status"] == "CONFIRMED"
        ira2 = get_success_data(api_client.get_safe_harbor_ira(ctx["ira2"]["id"], OPS))
        assert ira2["ira_status"] == "MATCHED"
