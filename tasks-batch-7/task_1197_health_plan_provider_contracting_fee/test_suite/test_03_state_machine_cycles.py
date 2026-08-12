"""Non-linear state machines: negotiation cycle and batch reopen cycle."""
from test_helpers import (
    get_success_data, validate_success,
    create_network, create_provider, create_draft_contract,
    create_simulation_claim_payload,
    make_contract_legal_headers, make_contract_manager_headers,
    setup_contract_in_testing,
    TEST_USERS,
)

CA = TEST_USERS["configuration_analyst_headers"]
CM = TEST_USERS["contract_manager_headers"]


class TestContractNegotiationCycle:
    def _build_pending(self, api):
        net = create_network()
        prov = create_provider()
        contract = create_draft_contract(network_id=net["id"], provider_id=prov["id"],
                                         escalator_bps=300)
        contract = get_success_data(api.begin_negotiation(contract["id"], CM))
        return contract

    def test_counter_offer_loops_back_and_clears_submitter(self, api):
        """PRD §3.3: "A counter-offer returns the contract from `PENDING_SIGNATURE`
        to `IN_NEGOTIATION`: `negotiation_round` increments by one (it accumulates
        across as many submit-counter-resubmit cycles as the negotiation
        requires), `submitted_by_user_id` is cleared to null"

        Design: Difficulty/non_linear_state_machine/contract_negotiation_cycle
        """
        contract = self._build_pending(api)
        submit_headers = make_contract_manager_headers("cm-1")
        get_success_data(api.submit_for_signature(contract["id"], submit_headers))
        after_counter = get_success_data(api.counter_offer(contract["id"], CM))
        assert after_counter["contract_status"] == "IN_NEGOTIATION"
        assert after_counter["negotiation_round"] == 1
        assert after_counter["submitted_by_user_id"] is None

    def test_two_cycles_accumulate_round_then_sign_exits(self, api):
        """PRD §3.3: "`negotiation_round` increments by one (it accumulates across
        as many submit-counter-resubmit cycles as the negotiation requires)"
        PRD §3.3: "A clean signature moves the contract from `PENDING_SIGNATURE`
        to `SIGNED`"

        Design: Difficulty/non_linear_state_machine/contract_negotiation_cycle
        """
        contract = self._build_pending(api)
        submit_headers = make_contract_manager_headers("cm-1")
        sign_headers = make_contract_legal_headers("cl-1")

        get_success_data(api.submit_for_signature(contract["id"], submit_headers))
        r1 = get_success_data(api.counter_offer(contract["id"], CM))
        get_success_data(api.submit_for_signature(contract["id"], submit_headers))
        r2 = get_success_data(api.counter_offer(contract["id"], CM))
        assert r1["negotiation_round"] == 1
        assert r2["negotiation_round"] == 2

        get_success_data(api.submit_for_signature(contract["id"], submit_headers))
        signed = get_success_data(api.sign_contract(contract["id"], sign_headers))
        assert signed["contract_status"] == "SIGNED"


class TestBatchFailedReopenCycle:
    def _setup_failed_batch(self, api):
        """Batch with 2 MATCH + 2 MISMATCH -> FAILED (20000 < 30000)."""
        artefacts = setup_contract_in_testing()
        batch_id = artefacts["batch"]["id"]
        # Two claims that will MATCH (expected == priced 10000)
        for d in ("2026-07-15", "2026-07-16"):
            get_success_data(api.create_simulation_claim(
                batch_id, create_simulation_claim_payload(service_date=d), CA))
        # Two claims that will MISMATCH (expected 9999 != priced 10000)
        for d in ("2026-07-17", "2026-07-18"):
            get_success_data(api.create_simulation_claim(
                batch_id,
                create_simulation_claim_payload(service_date=d, expected_allowed_cents=9999),
                CA))
        get_success_data(api.price_batch(batch_id, CA))
        return batch_id

    def test_failed_reopen_resets_claims_and_counters(self, api):
        """PRD §3.6: "Reopening — permitted only from `FAILED` — returns the batch
        to `OPEN` and compensates in full: every claim whose outcome was `MATCH`,
        `MISMATCH`, or `EXCLUDED` reverts to `PENDING` with its
        `priced_allowed_cents` reset to null, the matched, mismatched, and
        excluded counters return to zero, `pending_claims` is restored to
        `total_claims`, and `total_priced_cents` returns to zero."

        Design: Difficulty/non_linear_state_machine/batch_failed_reopen_cycle
        """
        batch_id = self._setup_failed_batch(api)
        failed = get_success_data(api.score_batch(batch_id, CA))
        assert failed["batch_status"] == "FAILED"

        reopened = get_success_data(api.reopen_batch(batch_id, CA))
        assert reopened["batch_status"] == "OPEN"
        assert reopened["pending_claims"] == 4
        assert reopened["matched_claims"] == 0
        assert reopened["mismatched_claims"] == 0
        assert reopened["excluded_claims"] == 0
        assert reopened["total_priced_cents"] == 0

        claims = get_success_data(api.list_simulation_claims(batch_id, TEST_USERS["plan_admin_headers"]))
        assert len(claims) == 4
        for c in claims:
            assert c["claim_outcome"] == "PENDING"
            assert c["priced_allowed_cents"] is None

    def test_reopen_cycle_is_repeatable(self, api):
        """PRD §3.6: "Reopening — permitted only from `FAILED` — returns the batch
        to `OPEN`"; PRD §3.6: "The batch passes when `matched_claims` multiplied
        by ten thousand is at least the priced population multiplied by 7,500
        basis points (75.00%)"

        Design: Difficulty/non_linear_state_machine/batch_failed_reopen_cycle
        """
        batch_id = self._setup_failed_batch(api)
        # First pass: FAILED
        first = get_success_data(api.score_batch(batch_id, CA))
        assert first["batch_status"] == "FAILED"
        get_success_data(api.reopen_batch(batch_id, CA))
        # Second pass after reopen: same deterministic outcome
        get_success_data(api.price_batch(batch_id, CA))
        second = get_success_data(api.score_batch(batch_id, CA))
        assert second["batch_status"] == "FAILED"
