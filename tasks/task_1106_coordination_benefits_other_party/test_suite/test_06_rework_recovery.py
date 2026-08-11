"""Claim rework cycle, financial invariants, and the recovery / reimbursement
pipeline (PRD §3.6, §3.7)."""
from test_helpers import (
    TEST_USERS,
    create_recovery_request_payload,
    create_reimbursement_payload,
    get_success_data,
    rework_paid_claim,
    setup_issued_recovery_request,
    setup_paid_secondary_claim,
    setup_secondary_position_claim,
    setup_repaid_claim_with_overpayment,
    validate_error,
    validate_success,
)

EXAMINER = TEST_USERS["claims_examiner_headers"]
RECOVERY = TEST_USERS["recovery_specialist_headers"]


class TestClaimReworkCycle:
    def test_rework_cycle_reaches_repaid_with_rework_count_one(self, api):
        """PRD §3.7: "Reopening moves the claim from `PAID` to `REOPENED`,
        increments `rework_cycle_count` by one, and increments the claim's
        `version`." and "Repayment then moves it from `READJUDICATED` to
        `REPAID`".

        Design: Difficulty/non_linear_state_machine/claim_rework_cycle_paid_to_repaid
        """
        ctx = setup_paid_secondary_claim()
        result = rework_paid_claim(
            ctx["claim"]["id"],
            cause="NEW_COVERAGE_DISCOVERED",
            triggering_determination_id=ctx["determination"]["id"],
        )
        claim = result["claim"]
        assert claim["status"] == "REPAID"
        assert claim["rework_cycle_count"] == 1

    def test_reopen_intermediate_state_and_count_increment(self, api):
        """PRD §3.7: "A `RecoverySpecialist` reopens a claim — only a `PAID`
        claim can be reopened — and the reopen must be backed by a triggering
        claim adjustment whose `cause` is one of `NEW_COVERAGE_DISCOVERED`,
        `PRIMACY_DETERMINATION_SUPERSEDED`, or `MSP_QUESTIONNAIRE_ADJUDICATED`"
        and "Reopening moves the claim from `PAID` to `REOPENED`, increments
        `rework_cycle_count` by one".

        Design: Difficulty/non_linear_state_machine/claim_rework_cycle_paid_to_repaid
        """
        ctx = setup_paid_secondary_claim()
        claim_id = ctx["claim"]["id"]
        adjustment = get_success_data(api.create_adjustment(
            claim_id, {
                "cause": "NEW_COVERAGE_DISCOVERED",
                "triggering_determination_id": ctx["determination"]["id"],
            }, EXAMINER,
        ))
        get_success_data(api.apply_adjustment(claim_id, adjustment["id"], EXAMINER))

        reopened = validate_success(api.reopen_claim(claim_id, RECOVERY), 200)
        assert reopened["status"] == "REOPENED"
        assert reopened["rework_cycle_count"] == 1

        get_success_data(api.readjudicate_claim(claim_id, EXAMINER))
        repaid = validate_success(api.repay_claim(claim_id, EXAMINER), 200)
        assert repaid["status"] == "REPAID"


class TestClaimFinancialInvariant:
    def test_secondary_totals_reconcile_at_adjudication(self, api):
        """PRD §3.6: "each line's `paid_cents` is the greater of zero and the
        amount by which the lesser of `allowed_cents` and `billed_cents` exceeds
        the line's `primary_paid_cents`" — with allowed 40000 and primary_paid
        25000 this plan pays 15000, and 15000 + 25000 = 40000.

        Design: Difficulty/compensating_invariant/claim_total_paid_conserved_through_rework_cycle
        """
        ctx = setup_secondary_position_claim(
            line_specs=[dict(billed_cents=50000, allowed_cents=40000,
                             primary_paid_cents=25000)]
        )
        claim = ctx["claim"]
        assert claim["total_allowed_cents"] == 40000
        assert claim["total_paid_cents"] + claim["total_primary_paid_cents"] == 40000

    def test_secondary_totals_reconcile_after_full_rework_cycle(self, api):
        """PRD §3.7: "recomputes each line's `paid_cents` against the new
        determination's `ordered_coverage_ids` and the claim's
        `total_paid_cents`, moving the claim from `REOPENED` to `READJUDICATED`".
        The same determination drives readjudication here, so the conservation
        total_paid + total_primary_paid == total_allowed must still hold after
        the cycle.

        Design: Difficulty/compensating_invariant/claim_total_paid_conserved_through_rework_cycle
        """
        ctx = setup_paid_secondary_claim(
            line_specs=[dict(billed_cents=50000, allowed_cents=40000,
                             primary_paid_cents=25000)]
        )
        result = rework_paid_claim(
            ctx["claim"]["id"],
            cause="NEW_COVERAGE_DISCOVERED",
            triggering_determination_id=ctx["determination"]["id"],
        )
        final = validate_success(api.get_claim(result["claim"]["id"], EXAMINER), 200)
        assert final["total_allowed_cents"] == 40000
        assert final["total_paid_cents"] + final["total_primary_paid_cents"] == 40000


class TestOverrecoveryBoundary:
    def test_reimbursement_of_exact_remaining_balance_fully_recovers(self, api):
        """PRD §3.7: "A reimbursement may not exceed the remaining unrecovered
        balance, that is, the request's `amount_cents` minus its
        `amount_recovered_cents` at posting time; an excess is rejected with
        `ERR_OVERRECOVERY` (HTTP 422)." Posting exactly the remaining balance is
        within the cap: "when `amount_recovered_cents` reaches `amount_cents`
        the request becomes `FULLY_RECOVERED`".

        Design: Difficulty/boundary_precision_check/overrecovery_at_exact_remaining_balance
        """
        ctx = setup_issued_recovery_request()  # overpayment == 10000
        claim_id, recovery = ctx["claim"]["id"], ctx["recovery"]
        get_success_data(api.post_reimbursement(
            claim_id, recovery["id"], create_reimbursement_payload(6000), RECOVERY,
        ))
        res = api.post_reimbursement(
            claim_id, recovery["id"], create_reimbursement_payload(4000), RECOVERY,
        )
        validate_success(res, 201)
        after = validate_success(api.get_recovery_request(claim_id, recovery["id"], RECOVERY), 200)
        assert after["amount_recovered_cents"] == 10000
        assert after["status"] == "FULLY_RECOVERED"

    def test_reimbursement_one_cent_over_remaining_rejected(self, api):
        """PRD §3.7: "A reimbursement may not exceed the remaining unrecovered
        balance, that is, the request's `amount_cents` minus its
        `amount_recovered_cents` at posting time; an excess is rejected with
        `ERR_OVERRECOVERY` (HTTP 422)." Remaining is 4000 after a 6000 posting;
        4001 exceeds it.

        Design: Difficulty/boundary_precision_check/overrecovery_at_exact_remaining_balance
        """
        ctx = setup_issued_recovery_request()  # overpayment == 10000
        claim_id, recovery = ctx["claim"]["id"], ctx["recovery"]
        get_success_data(api.post_reimbursement(
            claim_id, recovery["id"], create_reimbursement_payload(6000), RECOVERY,
        ))
        res = api.post_reimbursement(
            claim_id, recovery["id"], create_reimbursement_payload(4001), RECOVERY,
        )
        validate_error(res, "ERR_OVERRECOVERY", expected_status=422)


class TestRecoveryBalanceConsistency:
    def test_partial_postings_accumulate_to_full_recovery(self, api):
        """PRD §3.7: "Each posting adds its amount to `amount_recovered_cents`,
        and the request's status follows the money automatically: the first
        partial posting moves it from `ISSUED` to `PARTIALLY_RECOVERED`, and
        when `amount_recovered_cents` reaches `amount_cents` the request becomes
        `FULLY_RECOVERED`".

        Design: Difficulty/compensating_invariant/recovery_amount_recovered_consistency_after_reimbursements
        """
        ctx = setup_issued_recovery_request()  # overpayment == 10000
        claim_id, recovery = ctx["claim"]["id"], ctx["recovery"]

        get_success_data(api.post_reimbursement(
            claim_id, recovery["id"], create_reimbursement_payload(3000), RECOVERY,
        ))
        mid = validate_success(api.get_recovery_request(claim_id, recovery["id"], RECOVERY), 200)
        assert mid["amount_recovered_cents"] == 3000
        assert mid["status"] == "PARTIALLY_RECOVERED"

        get_success_data(api.post_reimbursement(
            claim_id, recovery["id"],
            create_reimbursement_payload(4000, method="OFFSET_AGAINST_FUTURE_CLAIMS"),
            RECOVERY,
        ))
        get_success_data(api.post_reimbursement(
            claim_id, recovery["id"],
            create_reimbursement_payload(3000, method="CARRIER_TO_CARRIER_TRANSFER"),
            RECOVERY,
        ))
        after = validate_success(api.get_recovery_request(claim_id, recovery["id"], RECOVERY), 200)
        assert after["amount_recovered_cents"] == 10000
        assert after["amount_recovered_cents"] == after["amount_cents"]
        assert after["status"] == "FULLY_RECOVERED"

    def test_single_full_reimbursement_moves_issued_directly_to_fully_recovered(self, api):
        """PRD §3.7: "a single reimbursement covering the full amount moves an
        `ISSUED` request directly to `FULLY_RECOVERED`, with
        `amount_recovered_cents` set equal to `amount_cents`."

        Design: Difficulty/compensating_invariant/recovery_amount_recovered_consistency_after_reimbursements
        """
        ctx = setup_issued_recovery_request()  # overpayment == 10000
        claim_id, recovery = ctx["claim"]["id"], ctx["recovery"]
        assert recovery["status"] == "ISSUED"

        get_success_data(api.post_reimbursement(
            claim_id, recovery["id"], create_reimbursement_payload(10000), RECOVERY,
        ))
        after = validate_success(api.get_recovery_request(claim_id, recovery["id"], RECOVERY), 200)
        assert after["status"] == "FULLY_RECOVERED"
        assert after["amount_recovered_cents"] == after["amount_cents"]


class TestClaimCloseGating:
    def test_close_blocked_while_recovery_still_issued(self, api):
        """PRD §3.7: "A claim can finally be closed — moving from `REPAID` to
        `CLOSED` by a `RecoverySpecialist` — only when every recovery request
        against it is terminal, meaning `FULLY_RECOVERED` or `WRITTEN_OFF`".
        An ISSUED request is not terminal, so the transition is invalid
        (`ERR_INVALID_STATE`, §2.9 family 4).

        Design: Difficulty/cross_entity_state_dependency/claim_close_requires_all_recoveries_terminal
        """
        ctx = setup_issued_recovery_request()
        assert ctx["recovery"]["status"] == "ISSUED"
        res = api.close_claim(ctx["claim"]["id"], RECOVERY)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_close_succeeds_once_recovery_fully_recovered(self, api):
        """PRD §3.7: "A claim can finally be closed — moving from `REPAID` to
        `CLOSED` by a `RecoverySpecialist` — only when every recovery request
        against it is terminal, meaning `FULLY_RECOVERED` or `WRITTEN_OFF`;
        closure increments the claim's `version`."

        Design: Difficulty/cross_entity_state_dependency/claim_close_requires_all_recoveries_terminal
        """
        ctx = setup_issued_recovery_request()
        claim_id, recovery = ctx["claim"]["id"], ctx["recovery"]
        get_success_data(api.post_reimbursement(
            claim_id, recovery["id"],
            create_reimbursement_payload(ctx["overpayment"]), RECOVERY,
        ))
        closed = validate_success(api.close_claim(claim_id, RECOVERY), 200)
        assert closed["status"] == "CLOSED"


def test_recovery_escalate_before_due_date_rejected(api):
    """PRD §3.7: "Escalating an `ISSUED` request requires the current clock to
    be later than `due_date` with `amount_recovered_cents` still below
    `amount_cents`; a request not yet past due is rejected with
    `ERR_NOT_PAST_DUE` (HTTP 409)".

    Design: Corner/state_machines/recovery_escalate_before_due_date_rejected
    """
    ctx = setup_issued_recovery_request()
    res = api.escalate_recovery_request(ctx["claim"]["id"], ctx["recovery"]["id"], RECOVERY)
    validate_error(res, "ERR_NOT_PAST_DUE", expected_status=409)
