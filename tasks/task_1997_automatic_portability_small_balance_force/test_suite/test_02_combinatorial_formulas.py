"""Queue A difficulty tests: combinatorial formulas (match score, withholding, transfer)."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    setup_established_ira,
    setup_matched_ira,
    setup_transfer_ready_ira,
    setup_ira_with_fee_disclosure,
    setup_second_active_recordkeeper_and_plan,
    initiate_transfer,
)

OPS = TEST_USERS["provider_ops_headers"]


class TestMatchScoreWeightedGateBanding:
    def test_weighted_score_and_sibling_expiry(self):
        """PRD §3.7: "The `match_score` adds three contributions — 0.55 when `ssn_exact` is
        true, thirty percent of `name_similarity`, and 0.15 when `dob_match` is true — and
        rounds the sum half-up to three decimal places."
        PRD §3.7: "Confirmation — automatic or manual — flips the IRA from `OPEN` to
        `MATCHED` and expires every other `CANDIDATE` of the same IRA to `EXPIRED`, keeping
        at most one `CONFIRMED` match per IRA at any time."

        Design: Difficulty/combinatorial_formula/match_score_weighted_gate_banding
        """
        ctx = setup_established_ira(balance=300000)
        rk_b, plan_y = setup_second_active_recordkeeper_and_plan()
        m1 = validate_success(api_client.create_match_search(
            ctx["ira"]["id"],
            {"new_plan_id": plan_y["id"], "new_recordkeeper_id": rk_b["id"],
             "employment_start_date": "2026-08-10", "ssn_exact": True,
             "name_similarity": 0.34, "dob_match": False},
            OPS,
        ), 201)
        assert m1["match_score"] == pytest.approx(0.652, abs=1e-9)
        assert m1["match_status"] == "CANDIDATE"

        m2 = validate_success(api_client.create_match_search(
            ctx["ira"]["id"],
            {"new_plan_id": plan_y["id"], "new_recordkeeper_id": rk_b["id"],
             "employment_start_date": "2026-08-12", "ssn_exact": True,
             "name_similarity": 0.70, "dob_match": True},
            OPS,
        ), 201)
        assert m2["match_score"] == pytest.approx(0.910, abs=1e-9)
        assert m2["match_status"] == "CONFIRMED"

        m1_after = get_success_data(api_client.get_match_candidate(m1["id"], OPS))
        assert m1_after["match_status"] == "EXPIRED"
        ira_after = get_success_data(api_client.get_safe_harbor_ira(ctx["ira"]["id"], OPS))
        assert ira_after["ira_status"] == "MATCHED"

    def test_weighted_score_values(self):
        """PRD §3.7: "A score of at least 0.400 but below 0.850 parks the candidate in
        `CANDIDATE`, the manual-review queue"
        PRD §3.7: "A score of at least 0.850 confirms immediately, but only when
        `ssn_exact` is true"

        Design: Difficulty/combinatorial_formula/match_score_weighted_gate_banding
        """
        ctx = setup_established_ira(balance=300000)
        rk_b, plan_y = setup_second_active_recordkeeper_and_plan()
        m1 = validate_success(api_client.create_match_search(
            ctx["ira"]["id"],
            {"new_plan_id": plan_y["id"], "new_recordkeeper_id": rk_b["id"],
             "employment_start_date": "2026-08-10", "ssn_exact": True,
             "name_similarity": 0.34, "dob_match": False},
            OPS,
        ), 201)
        # 0.55 + 0.30 * 0.34 = 0.652, in [0.400, 0.850) so CANDIDATE
        assert m1["match_status"] == "CANDIDATE"
        assert m1["match_score"] == pytest.approx(0.652, abs=1e-9)


class TestWithholdingPerComponentRoundingOrder:
    def test_per_component_rounding(self):
        """PRD §3.5: "The rounding order is pinned — each component is rounded to integer
        cents first and only then subtracted; netting a combined rate against the gross in a
        single step is a different, forbidden order that can drift the result by a cent."
        PRD §3.5: "`fed_withholding_cents` is twenty percent of the gross, rounded half-up
        to integer cents; `state_withholding_cents` is the gross times the plan's
        `state_withholding_rate`, rounded half-up to integer cents; and the payable
        `amount_cents` is the gross minus the two rounded components."

        Design: Difficulty/combinatorial_formula/withholding_per_component_rounding_order
        """
        from test_helpers import (
            create_active_recordkeeper, create_plan, create_participant,
            create_open_batch, create_case, send_force_out_notice_and_deliver,
            submit_election, make_provider_ops_headers,
        )
        SPONSOR = TEST_USERS["plan_sponsor_headers"]
        rk = create_active_recordkeeper()
        plan = create_plan(rk["id"], state_withholding_rate=0.05)
        p_a = create_participant()
        batch = create_open_batch(plan["id"])
        case = create_case(batch["id"], plan["id"], p_a["id"],
                           separation_date_balance_cents=100007,
                           processing_date_balance_cents=100007)
        get_success_data(api_client.lock_distribution_batch(batch["id"], SPONSOR))
        send_force_out_notice_and_deliver(case["id"])
        submit_election(case["id"], p_a["id"], "LUMP_SUM_CASH")
        get_success_data(api_client.execute_distribution_batch(
            batch["id"], make_provider_ops_headers("ops_exec_1")))

        chk = validate_success(api_client.create_check(
            {"distribution_case_id": case["id"]}, OPS), 201)
        assert chk["gross_amount_cents"] == 100007
        # round_half_up(100007 * 0.20) = round_half_up(20001.40) = 20001
        assert chk["fed_withholding_cents"] == 20001
        # round_half_up(100007 * 0.05) = round_half_up(5000.35) = 5000
        assert chk["state_withholding_cents"] == 5000
        # Per-component order: 100007 - 20001 - 5000 = 75006
        # (sum-then-round of the combined 0.25 rate would yield 75005 — forbidden)
        assert chk["amount_cents"] == 75006

    def test_per_component_rounding_net_is_gross_minus_components(self):
        """PRD §3.5: "the payable `amount_cents` is the gross minus the two rounded
        components."
        PRD §2.6: "Every monetary rounding in the system is round half-up to integer cents"

        Design: Difficulty/combinatorial_formula/withholding_per_component_rounding_order
        """
        from test_helpers import (
            create_active_recordkeeper, create_plan, create_participant,
            create_open_batch, create_case, send_force_out_notice_and_deliver,
            submit_election, make_provider_ops_headers,
        )
        SPONSOR = TEST_USERS["plan_sponsor_headers"]
        rk = create_active_recordkeeper()
        plan = create_plan(rk["id"], state_withholding_rate=0.05)
        p_a = create_participant()
        batch = create_open_batch(plan["id"])
        case = create_case(batch["id"], plan["id"], p_a["id"],
                           separation_date_balance_cents=100007,
                           processing_date_balance_cents=100007)
        get_success_data(api_client.lock_distribution_batch(batch["id"], SPONSOR))
        send_force_out_notice_and_deliver(case["id"])
        submit_election(case["id"], p_a["id"], "LUMP_SUM_CASH")
        get_success_data(api_client.execute_distribution_batch(
            batch["id"], make_provider_ops_headers("ops_exec_1")))
        chk = validate_success(api_client.create_check(
            {"distribution_case_id": case["id"]}, OPS), 201)
        assert (chk["amount_cents"]
                == chk["gross_amount_cents"]
                - chk["fed_withholding_cents"]
                - chk["state_withholding_cents"])


class TestTransferAmountEvaluationOrder:
    def _setup(self):
        """IRA funded 300000 ACTUAL_365, one posted fee at 2026-09-01 (510),
        prenotice delivered 2026-08-01, CONFIRMED match, clock 2026-09-16."""
        from test_helpers import (
            create_active_recordkeeper, create_plan, create_participant,
            create_open_batch, create_case, send_force_out_notice_and_deliver,
            submit_election, make_provider_ops_headers,
            setup_second_active_recordkeeper_and_plan,
        )
        SPONSOR = TEST_USERS["plan_sponsor_headers"]
        rk = create_active_recordkeeper()
        rk_b, plan_y = setup_second_active_recordkeeper_and_plan()
        plan = create_plan(rk["id"])
        p_a = create_participant()
        batch = create_open_batch(plan["id"])
        case = create_case(batch["id"], plan["id"], p_a["id"],
                           separation_date_balance_cents=300000,
                           processing_date_balance_cents=300000)
        get_success_data(api_client.lock_distribution_batch(batch["id"], SPONSOR))
        send_force_out_notice_and_deliver(case["id"])
        submit_election(case["id"], p_a["id"], "SAFE_HARBOR_IRA")
        get_success_data(api_client.execute_distribution_batch(
            batch["id"], make_provider_ops_headers("ops_exec_1")))
        ira = get_success_data(api_client.create_safe_harbor_ira(
            {"distribution_case_id": case["id"],
             "fee_day_count_convention": "ACTUAL_365"}, OPS))
        fd = get_success_data(api_client.create_notice(
            case["id"], {"notice_type": "FEE_DISCLOSURE"}, OPS))
        get_success_data(api_client.record_notice_delivery(
            fd["id"], {"outcome": "DELIVERED"}, OPS))
        pre = get_success_data(api_client.create_notice(
            case["id"], {"notice_type": "AUTO_PORTABILITY_PRENOTICE"}, OPS))
        get_success_data(api_client.record_notice_delivery(
            pre["id"], {"outcome": "DELIVERED"}, OPS))
        # Post one fee at 2026-09-01 (510 cents for August under ACTUAL_365).
        get_success_data(api_client.set_clock("2026-09-01T00:00:00Z", OPS))
        get_success_data(api_client.assess_ira_fee(ira["id"], OPS))
        get_success_data(api_client.create_match_search(
            ira["id"],
            {"new_plan_id": plan_y["id"], "new_recordkeeper_id": rk_b["id"],
             "employment_start_date": "2026-08-10", "ssn_exact": True,
             "name_similarity": 0.90, "dob_match": True},
            OPS,
        ))
        get_success_data(api_client.set_clock("2026-09-16T00:00:00Z", OPS))
        return ira

    def test_transfer_amount_snapshot_minus_accrual(self):
        """PRD §3.7: "first, snapshot the IRA's `balance_cents`, already net of every
        posted fee; second, compute the accrued-but-unbilled maintenance fee from the fee
        anchor — `last_fee_assessed_at`, or `opened_at` when never assessed — to the
        current instant under the IRA's day-count convention, but without the balance cap
        that a posted assessment would apply; third, subtract the accrual from the
        snapshot."

        Design: Difficulty/combinatorial_formula/transfer_amount_evaluation_order
        """
        ira = self._setup()
        ira_fresh = get_success_data(api_client.get_safe_harbor_ira(ira["id"], OPS))
        transfer = validate_success(api_client.create_transfer(
            ira["id"], {"expected_ira_version": ira_fresh["version"]}, OPS), 201)
        # Snapshot after posted fee: 299490. Accrual 2026-09-01 -> 2026-09-16 is
        # 15 days ACTUAL_365: round_half_up(6000 * 15 / 365) = 247.
        assert transfer["amount_cents"] == 299243
        assert transfer["accrued_fee_offset_cents"] == 247

    def test_transfer_moves_balance_to_in_flight(self):
        """PRD §3.7: "`balance_cents` drops by the amount, `in_flight_cents` rises by the
        same, `last_activity_at` refreshes, and the IRA's `version` increments."

        Design: Difficulty/combinatorial_formula/transfer_amount_evaluation_order
        """
        ira = self._setup()
        ira_fresh = get_success_data(api_client.get_safe_harbor_ira(ira["id"], OPS))
        validate_success(api_client.create_transfer(
            ira["id"], {"expected_ira_version": ira_fresh["version"]}, OPS), 201)
        after = get_success_data(api_client.get_safe_harbor_ira(ira["id"], OPS))
        assert after["balance_cents"] == 247
        assert after["in_flight_cents"] == 299243
        assert after["ira_status"] == "TRANSFER_PENDING"
