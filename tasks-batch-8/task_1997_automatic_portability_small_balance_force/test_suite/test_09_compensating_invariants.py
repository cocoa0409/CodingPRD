"""Queue A difficulty tests: compensating invariants (IRA money conservation, check chains)."""
from test_helpers import (
    api_client,
    validate_success,
    validate_paginated,
    get_success_data,
    TEST_USERS,
    setup_transfer_ready_ira,
    setup_executed_batch_elected_cash,
    initiate_transfer,
    assert_ira_money_conservation,
)

OPS = TEST_USERS["provider_ops_headers"]


class TestIraMoneyConservationTransferCycle:
    def _setup(self):
        return setup_transfer_ready_ira(balance=300000, clock="2026-09-01T00:00:00Z")

    def test_reject_compensation_restores_identity(self):
        """PRD §3.6: "The IRA's `balance_cents` is always explainable: it equals
        `funded_amount_cents` minus `total_fees_cents`, minus
        `total_transferred_out_cents`, minus `in_flight_cents`, and is maintained on every
        money event."
        PRD §3.7: "the IRA is re-credited — `in_flight_cents` down by the amount,
        `balance_cents` up by the same — and returns from `TRANSFER_PENDING` to `OPEN`"

        Design: Difficulty/compensating_invariant/ira_money_conservation_transfer_cycle
        """
        ctx = self._setup()
        ira = ctx["ira"]
        # Accrual from opened_at (2026-08-01) to 2026-09-01 = 31 days ACTUAL_365:
        # round_half_up(6000 * 31 / 365) = 510 withheld as accrued_fee_offset.
        tr1 = initiate_transfer(ira["id"])
        assert tr1["amount_cents"] == 299490
        assert tr1["accrued_fee_offset_cents"] == 510
        after_send = get_success_data(api_client.get_safe_harbor_ira(ira["id"], OPS))
        assert after_send["balance_cents"] == 510
        assert after_send["in_flight_cents"] == 299490
        assert_ira_money_conservation(after_send)

        # Compensation: rejection re-credits in_flight back to balance.
        validate_success(api_client.record_transfer_response(
            tr1["id"], {"outcome": "REJECTED",
                        "rejection_reason": "account mismatch"}, OPS))
        after_reject = get_success_data(api_client.get_safe_harbor_ira(ira["id"], OPS))
        assert after_reject["balance_cents"] == 300000
        assert after_reject["in_flight_cents"] == 0
        assert after_reject["total_transferred_out_cents"] == 0
        assert_ira_money_conservation(after_reject)

    def test_accepted_transfer_completes_identity(self):
        """PRD §3.6: "The IRA's `balance_cents` is always explainable: it equals
        `funded_amount_cents` minus `total_fees_cents`, minus
        `total_transferred_out_cents`, minus `in_flight_cents`, and is maintained on every
        money event."
        PRD §3.7: "Acceptance reconciles everything: the transfer moves to `RECONCILED`
        with `settled_at` stamped, the IRA's `in_flight_cents` drops by the amount while
        `total_transferred_out_cents` rises by the same, `last_activity_at` refreshes, the
        IRA settles in `TRANSFERRED_OUT`, and the transfer's `version` increments."

        Design: Difficulty/compensating_invariant/ira_money_conservation_transfer_cycle
        """
        ctx = self._setup()
        ira = ctx["ira"]
        tr1 = initiate_transfer(ira["id"])
        validate_success(api_client.record_transfer_response(
            tr1["id"], {"outcome": "REJECTED",
                        "rejection_reason": "account mismatch"}, OPS))
        # Fresh match on the reopened IRA, then a second transfer that is ACCEPTED.
        get_success_data(api_client.create_match_search(
            ira["id"],
            {"new_plan_id": ctx["plan_y"]["id"],
             "new_recordkeeper_id": ctx["rk_b"]["id"],
             "employment_start_date": "2026-08-10", "ssn_exact": True,
             "name_similarity": 0.90, "dob_match": True},
            OPS,
        ))
        tr2 = initiate_transfer(ira["id"])
        validate_success(api_client.record_transfer_response(
            tr2["id"], {"outcome": "ACCEPTED"}, OPS))
        after = get_success_data(api_client.get_safe_harbor_ira(ira["id"], OPS))
        assert after["ira_status"] == "TRANSFERRED_OUT"
        assert after["balance_cents"] == 510
        assert after["in_flight_cents"] == 0
        assert after["total_transferred_out_cents"] == 299490
        assert after["total_fees_cents"] == 0
        assert_ira_money_conservation(after)


class TestCheckChainObligationConservation:
    def _setup(self):
        """Elected LUMP_SUM_CASH case (vested 100000, default rate 0) EXECUTED; check C1
        ISSUED at the default clock, then swept STALE_DATED at 2027-01-29."""
        ctx = setup_executed_batch_elected_cash(balance=100000)
        chk1 = get_success_data(api_client.create_check(
            {"distribution_case_id": ctx["case"]["id"]}, OPS))
        get_success_data(api_client.set_clock("2027-01-29T00:00:00Z", OPS))
        get_success_data(api_client.run_sweep(OPS))
        ctx["chk1"] = get_success_data(api_client.get_check(chk1["id"], OPS))
        return ctx

    def test_void_reissue_preserves_obligation(self):
        """PRD §3.8: "The reissue spawns a successor check, `ISSUED` fresh, with its
        `supersedes_check_id` pointing at the predecessor — that field is null on a first
        issue — carrying identical amount fields and a fresh `issued_at` and `stale_after`;
        the predecessor row stays `VOIDED`, so the chain of custody is preserved end to
        end."
        PRD §3.5: "`fed_withholding_cents` is twenty percent of the gross, rounded half-up
        to integer cents; `state_withholding_cents` is the gross times the plan's
        `state_withholding_rate`, rounded half-up to integer cents; and the payable
        `amount_cents` is the gross minus the two rounded components."

        Design: Difficulty/compensating_invariant/check_chain_obligation_conservation
        """
        ctx = self._setup()
        chk1 = ctx["chk1"]
        assert chk1["check_status"] == "STALE_DATED"
        # Net at 0% state rate: 100000 - round_half_up(100000 * 0.20) - 0 = 80000.
        assert chk1["amount_cents"] == 80000
        assert chk1["fed_withholding_cents"] == 20000
        assert chk1["state_withholding_cents"] == 0
        # stale_after = issued_at + 180 days, issued at the 2026-08-01 default clock.
        assert chk1["stale_after"] == "2027-01-28T00:00:00.000Z"

        validate_success(api_client.void_check(chk1["id"], {"void_reason": "STALE"}, OPS))
        chk2 = validate_success(api_client.reissue_check(chk1["id"], OPS), 201)

        chk1_after = get_success_data(api_client.get_check(chk1["id"], OPS))
        assert chk1_after["check_status"] == "VOIDED"
        assert chk2["check_status"] == "ISSUED"
        assert chk2["supersedes_check_id"] == chk1["id"]
        assert chk2["amount_cents"] == 80000

    def test_cashing_successor_settles_exactly_once(self):
        """PRD §3.8: "Recording a cash is a `ProviderOps` action on an `ISSUED` check: it
        moves `check_status` from `ISSUED` to `CASHED`, stamps `cashed_at`, increments the
        check's `version`, and — for a check of `origin` `CASE_CASH_OUT` — settles the
        underlying case from `EXECUTED` to `SETTLED`"
        PRD §2.3: "List endpoints also accept exact-match filter parameters, each named
        after a resource field and matching resources whose like-named field equals the
        supplied value."

        Design: Difficulty/compensating_invariant/check_chain_obligation_conservation
        """
        ctx = self._setup()
        chk1 = ctx["chk1"]
        validate_success(api_client.void_check(chk1["id"], {"void_reason": "STALE"}, OPS))
        chk2 = validate_success(api_client.reissue_check(chk1["id"], OPS), 201)
        validate_success(api_client.record_check_cashed(chk2["id"], OPS))

        case = get_success_data(
            api_client.get_distribution_case(ctx["case"]["id"], OPS))
        assert case["case_status"] == "SETTLED"

        successors, meta = validate_paginated(api_client.list_checks(
            OPS, params={"supersedes_check_id": chk1["id"]}))
        assert meta["total_count"] == 1
        assert successors[0]["id"] == chk2["id"]
