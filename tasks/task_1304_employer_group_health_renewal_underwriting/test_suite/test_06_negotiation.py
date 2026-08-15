"""Negotiation: counter/respond cycles, rounds, proposer rules."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    api_client,
    create_counter_payload,
    create_respond_payload,
    setup_case_with_proposed_quote,
    setup_case_with_countered_quote,
    make_broker_headers,
    create_broker,
    create_broker_payload,
    TEST_USERS,
)

UW = TEST_USERS["underwriter_headers"]


class TestQuoteNegotiationCycle:
    def test_quote_proposed_countered_cycle_status_and_rounds(self):
        """PRD section 3.6: "The counter moves the quote from `PROPOSED` to
        `COUNTERED`, spawns a **Negotiation Round** record — numbered
        sequentially within the quote via `round_number` starting at 1, stamped
        `proposed_by` with `BROKER`, carrying the proposed figures and the
        quote's `quote_id` and grandparent `case_id` — and swings the parent
        case from `QUOTED` to `NEGOTIATING`."
        PRD section 3.6: "The response moves the quote back from `COUNTERED` to
        `PROPOSED`, spawns the underwriter's `UNDERWRITER`-attributed
        negotiation round on the same quote, and returns the parent case from
        `NEGOTIATING` to `QUOTED`."

        Design: Difficulty/non_linear_state_machine/quote_proposed_countered_cycle
        """
        broker, case, plan, quote = setup_case_with_proposed_quote()
        broker_headers = make_broker_headers(broker["id"])
        qid = quote["id"]

        quote = validate_success(
            api_client.counter_quote(qid, create_counter_payload(
                proposed_pepm_cents=5000, proposed_contribution_pct=0.85,
                justification="Client requests rate relief for budget cycle",
            ), broker_headers)
        )
        assert quote["status"] == "COUNTERED"
        assert quote["negotiation_round"] == 1

        quote = validate_success(
            api_client.respond_quote(qid, create_respond_payload(
                proposed_pepm_cents=5200, proposed_contribution_pct=0.82,
                justification="Final offer after full experience review",
            ), UW)
        )
        assert quote["status"] == "PROPOSED"
        assert quote["negotiation_round"] == 2

        quote = validate_success(
            api_client.counter_quote(qid, create_counter_payload(
                proposed_pepm_cents=5100, proposed_contribution_pct=0.84,
                justification="Second counter with slightly higher contribution",
            ), broker_headers)
        )
        assert quote["status"] == "COUNTERED"
        assert quote["negotiation_round"] == 3

        rounds, meta = validate_paginated(api_client.list_negotiation_rounds(qid, UW))
        assert meta["total_count"] == 3
        assert quote["pepm_rate_cents"] == 5338

    def test_quote_cycle_preserves_quote_number_and_rate(self):
        """PRD section 3.6: "In this way the case oscillates `QUOTED →
        NEGOTIATING → QUOTED` while the parties trade rounds, and the quote's
        `negotiation_round` reflects the depth of the exchange."

        Design: Difficulty/non_linear_state_machine/quote_proposed_countered_cycle
        """
        broker, case, plan, quote = setup_case_with_proposed_quote()
        broker_headers = make_broker_headers(broker["id"])
        qid = quote["id"]
        original_number = quote["quote_number"]

        validate_success(api_client.counter_quote(qid, create_counter_payload(),
                                                  broker_headers))
        quote = validate_success(
            api_client.respond_quote(qid, create_respond_payload(), UW)
        )
        assert quote["quote_number"] == original_number
        assert quote["pepm_rate_cents"] == 5338
        assert quote["annual_premium_cents"] == 25622400
        assert quote["negotiation_round"] == 2


class TestCaseNegotiationCycle:
    def test_case_quoted_negotiating_cycle(self):
        """PRD section 3.6: "In this way the case oscillates `QUOTED →
        NEGOTIATING → QUOTED` while the parties trade rounds".

        Design: Difficulty/non_linear_state_machine/case_quoted_negotiating_cycle
        """
        broker, case, plan, quote = setup_case_with_proposed_quote()
        broker_headers = make_broker_headers(broker["id"])
        qid, cid = quote["id"], case["id"]

        validate_success(api_client.counter_quote(
            qid, create_counter_payload(
                proposed_pepm_cents=5000, proposed_contribution_pct=0.85,
                justification="Round one counter for budget relief",
            ), broker_headers))
        case1 = get_success_data(api_client.get_case(cid, UW))
        assert case1["status"] == "NEGOTIATING"

        validate_success(api_client.respond_quote(
            qid, create_respond_payload(
                proposed_pepm_cents=5200, proposed_contribution_pct=0.82,
                justification="Round one response with modest concession",
            ), UW))
        case2 = get_success_data(api_client.get_case(cid, UW))
        assert case2["status"] == "QUOTED"

        quote = validate_success(api_client.counter_quote(
            qid, create_counter_payload(
                proposed_pepm_cents=5150, proposed_contribution_pct=0.83,
                justification="Round two counter splitting the difference",
            ), broker_headers))
        case3 = get_success_data(api_client.get_case(cid, UW))
        assert case3["status"] == "NEGOTIATING"
        assert quote["status"] == "COUNTERED"
        assert quote["negotiation_round"] == 3

    def test_case_cycle_quote_never_leaves_own_cycle(self):
        """PRD section 3.6: "The response moves the quote back from `COUNTERED`
        to `PROPOSED`, spawns the underwriter's `UNDERWRITER`-attributed
        negotiation round on the same quote, and returns the parent case from
        `NEGOTIATING` to `QUOTED`."

        Design: Difficulty/non_linear_state_machine/case_quoted_negotiating_cycle
        """
        broker, case, plan, quote = setup_case_with_proposed_quote()
        broker_headers = make_broker_headers(broker["id"])
        qid, cid = quote["id"], case["id"]

        for i in range(2):
            validate_success(api_client.counter_quote(
                qid, create_counter_payload(
                    justification=f"Counter round {i + 1} for budget relief",
                ), broker_headers))
            assert get_success_data(api_client.get_case(cid, UW))["status"] == "NEGOTIATING"
            validate_success(api_client.respond_quote(
                qid, create_respond_payload(
                    justification=f"Response round {i + 1} with concession",
                ), UW))
            assert get_success_data(api_client.get_case(cid, UW))["status"] == "QUOTED"
            q = get_success_data(api_client.get_quote(qid, UW))
            assert q["status"] == "PROPOSED"


class TestNegotiationInvariant:
    def test_negotiation_cycle_conserves_quote_rate_and_case_state(self):
        """PRD section 3.6: "The response moves the quote back from `COUNTERED`
        to `PROPOSED`, spawns the underwriter's `UNDERWRITER`-attributed
        negotiation round on the same quote, and returns the parent case from
        `NEGOTIATING` to `QUOTED`."

        Design: Difficulty/compensating_invariant/negotiation_cycle_conserves_quote_rate_and_case_state
        """
        broker, case, plan, quote = setup_case_with_proposed_quote()
        broker_headers = make_broker_headers(broker["id"])
        qid, cid = quote["id"], case["id"]

        validate_success(api_client.counter_quote(
            qid, create_counter_payload(), broker_headers))
        quote = validate_success(api_client.respond_quote(
            qid, create_respond_payload(), UW))

        assert quote["status"] == "PROPOSED"
        assert quote["pepm_rate_cents"] == 5338
        assert quote["annual_premium_cents"] == 25622400
        assert quote["negotiation_round"] == 2
        case = get_success_data(api_client.get_case(cid, UW))
        assert case["status"] == "QUOTED"

    def test_negotiation_cycle_no_quote_reaches_terminal_state(self):
        """PRD section 3.6: "Quotes can die in several other ways. Either the
        broker or the underwriter may reject a live quote — from `PROPOSED` or
        from `COUNTERED` — moving it to `REJECTED`." Absent such actions, the
        counter/respond cycle alone moves no quote to a terminal state.

        Design: Difficulty/compensating_invariant/negotiation_cycle_conserves_quote_rate_and_case_state
        """
        broker, case, plan, quote = setup_case_with_proposed_quote()
        broker_headers = make_broker_headers(broker["id"])
        qid, cid = quote["id"], case["id"]

        validate_success(api_client.counter_quote(qid, create_counter_payload(),
                                                  broker_headers))
        validate_success(api_client.respond_quote(qid, create_respond_payload(), UW))

        quotes, _meta = validate_paginated(api_client.list_quotes(cid, UW))
        terminal = {"ACCEPTED", "REJECTED", "EXPIRED", "SUPERSEDED"}
        assert sum(1 for q in quotes if q["status"] in terminal) == 0


class TestNegotiationGuards:
    def test_accept_countered_quote_fails(self):
        """PRD section 3.6: "Accepting a quote requires the quote to be
        `PROPOSED` (else `ERR_QUOTE_NOT_PROPOSED`)".

        Design: Corner/state_machines/accept_countered_quote_fails
        """
        broker, case, plan, quote, rnd = setup_case_with_countered_quote()
        broker_headers = make_broker_headers(broker["id"])
        resp = api_client.accept_quote(quote["id"], broker_headers)
        validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_PROPOSED)
        quote = get_success_data(api_client.get_quote(quote["id"], UW))
        assert quote["status"] == "COUNTERED"
        case = get_success_data(api_client.get_case(case["id"], UW))
        assert case["status"] == "NEGOTIATING"
        plan = get_success_data(api_client.get_plan_design(plan["id"], UW))
        assert plan["status"] == "MODELED"

    def test_counter_by_non_broker_of_record(self):
        """PRD section 2.1: "A broker who counters a case whose broker of record
        is someone else is rejected with `ERR_NOT_BROKER_OF_RECORD` (HTTP 403)."

        Design: Corner/validations/counter_by_non_broker_of_record
        """
        broker, case, plan, quote = setup_case_with_proposed_quote()
        other = create_broker(firm_name="Other Brokerage",
                              license_number="LIC-CA-2002", commission_pct=0.05)
        resp = api_client.counter_quote(
            quote["id"],
            create_counter_payload(justification="Interloper broker counter attempt"),
            make_broker_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_BROKER_OF_RECORD)
        quote = get_success_data(api_client.get_quote(quote["id"], UW))
        assert quote["status"] == "PROPOSED"
        case = get_success_data(api_client.get_case(case["id"], UW))
        assert case["status"] == "QUOTED"

    def test_respond_uncountered_quote_fails(self):
        """PRD section 3.6: "which requires the quote to be `COUNTERED` (else
        `ERR_QUOTE_NOT_COUNTERED`)".

        Design: Corner/validations/respond_uncountered_quote_fails
        """
        broker, case, plan, quote = setup_case_with_proposed_quote()
        resp = api_client.respond_quote(
            quote["id"],
            create_respond_payload(justification="Response without a live counter"),
            UW,
        )
        validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_COUNTERED)
        quote = get_success_data(api_client.get_quote(quote["id"], UW))
        assert quote["status"] == "PROPOSED"

    def test_respond_after_case_withdrawn_fails(self):
        """PRD section 3.6: "which requires the quote to be `COUNTERED` (else
        `ERR_QUOTE_NOT_COUNTERED`) and the case to be `NEGOTIATING` (else
        `ERR_CASE_NOT_NEGOTIATING`)."

        Design: Corner/validations/respond_after_case_withdrawn_fails
        """
        broker, case, plan, quote, rnd = setup_case_with_countered_quote()
        broker_headers = make_broker_headers(broker["id"])
        validate_success(api_client.withdraw_case(case["id"], broker_headers))
        resp = api_client.respond_quote(
            quote["id"],
            create_respond_payload(justification="Response after withdrawal should fail"),
            UW,
        )
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_NEGOTIATING)
        quote = get_success_data(api_client.get_quote(quote["id"], UW))
        assert quote["status"] == "COUNTERED"
        case = get_success_data(api_client.get_case(case["id"], UW))
        assert case["status"] == "WITHDRAWN"


class TestNegotiationRounds:
    def test_withdraw_round_by_non_proposer_fails_then_proposer_succeeds(self):
        """PRD section 3.6: "withdrawing a round requires the round to be
        `PROPOSED` (else `ERR_ROUND_NOT_PROPOSED`) and requires the caller to be
        the party recorded in `proposed_by` — only the proposer may withdraw
        (else `ERR_NOT_ROUND_PROPOSER`, HTTP 403) — moving the round to
        `WITHDRAWN`."

        Design: Corner/validations/withdraw_round_by_non_proposer_fails_then_proposer_succeeds
        """
        broker, case, plan, quote, rnd = setup_case_with_countered_quote()
        assert rnd["proposed_by"] == "BROKER"
        resp = api_client.withdraw_round(rnd["id"], UW)
        validate_error(resp, ApiErrorId.ERR_NOT_ROUND_PROPOSER)
        ok = api_client.withdraw_round(
            rnd["id"], make_broker_headers(broker["id"])
        )
        data = validate_success(ok)
        assert data["status"] == "WITHDRAWN"

    def test_withdraw_round_twice_fails(self):
        """PRD section 3.6: "withdrawing a round requires the round to be
        `PROPOSED` (else `ERR_ROUND_NOT_PROPOSED`)".

        Design: Corner/validations/withdraw_round_twice_fails
        """
        broker, case, plan, quote, rnd = setup_case_with_countered_quote()
        broker_headers = make_broker_headers(broker["id"])
        validate_success(api_client.withdraw_round(rnd["id"], broker_headers))
        resp = api_client.withdraw_round(rnd["id"], broker_headers)
        validate_error(resp, ApiErrorId.ERR_ROUND_NOT_PROPOSED)
        rnd = get_success_data(api_client.get_negotiation_round(rnd["id"], UW))
        assert rnd["status"] == "WITHDRAWN"

    def test_negotiation_rounds_rejected_when_quote_rejected(self):
        """PRD section 3.6: "Rounds also resolve automatically with their parent
        quote: when the quote is accepted, its outstanding rounds move to
        `ACCEPTED`; when the quote is rejected or superseded, they move to
        `REJECTED`."
        PRD section 3.6: "Either the broker or the underwriter may reject a live
        quote — from `PROPOSED` or from `COUNTERED` — moving it to `REJECTED`."

        Design: Corner/state_machines/negotiation_rounds_rejected_when_quote_rejected
        """
        broker, case, plan, quote, rnd = setup_case_with_countered_quote()
        broker_headers = make_broker_headers(broker["id"])
        quote = validate_success(api_client.reject_quote(quote["id"], broker_headers))
        assert quote["status"] == "REJECTED"
        rnd = get_success_data(api_client.get_negotiation_round(rnd["id"], UW))
        assert rnd["status"] == "REJECTED"
