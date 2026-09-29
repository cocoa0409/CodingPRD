"""The cyclic parts of the machine: pend self-loops, reprocessing and the parallel
payment dimension, plus the transitions the engine refuses."""
import pytest

from test_helpers import (
    ApiErrorId,
    claim_line_payload,
    finalize,
    get_authorization,
    get_claim,
    get_claim_lines,
    other_payer_payment_payload,
    post_other_payer_payment,
    setup_duplicate_pair,
    setup_exhausted_authorization_with_finalized_claim,
    setup_finalized_imaging_claim,
    setup_imaging_environment,
    setup_pend_cycle_then_cob_repost,
    submit_and_adjudicate,
    submit_claim,
    validate_error,
    void_claim,
)
from test_helpers.fixtures import CLAIMS_EXAMINER, CLAIMS_INTAKE, OPEN_SECONDARY_COVERAGE


class TestPendReprocessingCycle:
    def test_a_second_pass_on_a_pended_claim_pends_again_instead_of_erroring(self, api):
        """PRD §3.8: "`PENDED → PENDED` is a legitimate self-loop — the reprocessing cycle —
        in which the claim pends again, possibly with a *different* `pend_reason_code` than
        the previous pass produced."
        PRD §3.8: "All three increment `adjudication_pass`, refresh
        `last_adjudicated_by_user_id`, and append an `ADJUDICATE` event."

        Design: Difficulty/non_linear_state_machine/claim_pended_self_loop_then_adjudicated_back_to_received_on_cob_post
        """
        env = setup_pend_cycle_then_cob_repost()
        first, second = env["pass_1"], env["pass_2"]
        assert first["status"] == "PENDED"
        assert first["adjudication_pass"] == 1
        assert first["pend_reason_code"] == "PEND_AUTH_MISSING"
        assert second["status"] == "PENDED", "The self-loop must run, not raise an error"
        assert second["adjudication_pass"] == 2
        assert first["payment_status"] == "NOT_REMITTED"
        assert second["payment_status"] == "NOT_REMITTED", (
            "payment_status is untouched while status cycles"
        )

    def test_a_late_other_payer_posting_drives_an_adjudicated_claim_back_to_received(
        self, api
    ):
        """PRD §3.7: "From `ADJUDICATED` the claim goes **back** to `RECEIVED`, the
        transition `ADJUDICATED → RECEIVED`: a late other-payer payment invalidates the
        coordination-of-benefits arithmetic already performed, so every service line resets
        to `PENDING`, every per-line computed money field is zeroed, the units each `PRICED`
        line was holding are released back to its authorization, the claim's
        `total_allowed_cents`, `total_deductible_applied_cents`,
        `total_member_liability_cents` and `total_plan_paid_cents` are all zeroed, and
        `pricing_variant` returns to `UNPRICED`."
        PRD §3.9: "A claim can cycle `RECEIVED → PENDED → PENDED → ADJUDICATED` any number
        of times while `payment_status` sits untouched at `NOT_REMITTED`; the payment
        dimension moves only at finalization, and thereafter only into `REVERSED`, which is
        terminal for that dimension."

        Design: Difficulty/non_linear_state_machine/claim_pended_self_loop_then_adjudicated_back_to_received_on_cob_post
        """
        env = setup_pend_cycle_then_cob_repost()
        adjudicated = env["pass_3"]
        assert adjudicated["status"] == "ADJUDICATED"
        assert adjudicated["adjudication_pass"] == 3
        assert adjudicated["total_plan_paid_cents"] == 60000

        post_other_payer_payment(env["claim"]["id"], 15000, adjudicated["version"])

        claim = get_claim(env["claim"]["id"])
        assert claim["status"] == "RECEIVED"
        assert claim["total_allowed_cents"] == 0
        assert claim["total_plan_paid_cents"] == 0
        assert claim["pricing_variant"] == "UNPRICED"
        assert claim["adjudication_pass"] == 3, "A COB posting does not run a pass"
        assert claim["payment_status"] == "NOT_REMITTED"
        authorization = get_authorization(env["authorization"]["id"])
        assert authorization["units_consumed"] == 0
        assert authorization["status"] == "ACTIVE"


class TestAuthorizationConsumptionCycle:
    def test_voiding_a_claim_returns_an_exhausted_grant_to_partially_consumed(self, api):
        """PRD §3.9: "Fifth, because a line reversed, the authorization it was linked to has
        its `units_consumed` reduced by that line's `units`."
        PRD §3.9: "Sixth, because `units_consumed` moved, the authorization's `status` is
        re-derived: `EXHAUSTED → PARTIALLY_CONSUMED` when consumption now sits strictly
        between zero and `authorized_units`, and `PARTIALLY_CONSUMED → ACTIVE` when
        consumption reaches zero."

        Design: Difficulty/non_linear_state_machine/authorization_returns_from_exhausted_to_partially_consumed_after_void
        """
        env = setup_exhausted_authorization_with_finalized_claim()
        before = env["authorization_before_void"]
        assert before["status"] == "EXHAUSTED"
        assert before["units_consumed"] == 4

        void_claim(env["finalized_claim"]["id"], "VOID_PROVIDER_CORRECTION")

        after = get_authorization(env["authorization"]["id"])
        assert after["units_consumed"] == 2, "Only the voided claim's two units come back"
        assert after["status"] == "PARTIALLY_CONSUMED", (
            "An exhausted grant becomes usable again once consuming lines are reversed"
        )

    def test_the_void_reverses_only_its_own_paid_lines(self, api):
        """PRD §3.9: "First, the claim moves `FINALIZED → VOIDED`, which is terminal.
        Second, because the claim voided, its `payment_status` flips `REMITTED → REVERSED`."
        PRD §3.9: "Fourth, because the remittance voided, every service line standing at
        `PAID` flips `PAID → REVERSED`."

        Design: Difficulty/non_linear_state_machine/authorization_returns_from_exhausted_to_partially_consumed_after_void
        """
        env = setup_exhausted_authorization_with_finalized_claim()
        voided = void_claim(env["finalized_claim"]["id"], "VOID_PROVIDER_CORRECTION")
        assert voided["status"] == "VOIDED"
        assert voided["payment_status"] == "REVERSED"

        voided_lines = get_claim_lines(env["finalized_claim"]["id"])
        assert len(voided_lines) == 1
        assert voided_lines[0]["line_status"] == "REVERSED"

        untouched_lines = get_claim_lines(env["holder_claim"]["id"])
        assert len(untouched_lines) == 1
        assert untouched_lines[0]["line_status"] == "PRICED", (
            "The other claim's line keeps holding its units"
        )


class TestRefusedTransitions:
    def test_adjudicating_a_finalized_claim_returns_invalid_claim_state(self, api):
        """PRD §3.5: "A pass may be run from `RECEIVED` or from `PENDED`; attempting one on
        a claim that is `FINALIZED`, `VOIDED`, `ADJUSTED` or `DUPLICATE_REJECTED` is refused
        with `ERR_INVALID_CLAIM_STATE`."

        Design: Corner/state_machines/adjudicate_a_finalized_claim_returns_invalid_claim_state
        """
        env = setup_finalized_imaging_claim(
            plan_overrides={"plan_code": "SM-1", "name": "State Machine Plan"},
            claim_number="CLM-SM-1",
        )
        response = api.adjudicate_claim(env["claim"]["id"], CLAIMS_EXAMINER)
        validate_error(response, ApiErrorId.ERR_INVALID_CLAIM_STATE.value)

        claim = get_claim(env["claim"]["id"])
        assert claim["status"] == "FINALIZED"
        assert claim["adjudication_pass"] == 1, "The refused pass must not be counted"

    def test_voiding_a_received_claim_returns_claim_not_finalized(self, api):
        """PRD §3.9: "**Voiding** unwinds a finalized claim completely, and it is refused
        with `ERR_CLAIM_NOT_FINALIZED` from any status other than `FINALIZED`."

        Design: Corner/state_machines/void_a_received_claim_returns_claim_not_finalized
        """
        env = setup_imaging_environment(
            plan_overrides={"plan_code": "SM-2", "name": "State Machine Plan Two"},
            member_overrides={"member_number": "M-SM-2"},
        )
        claim = submit_claim(
            env["member"]["id"],
            env["provider"]["id"],
            [claim_line_payload(1, "73721", 1, 60000, "2026-02-10")],
            "CLM-SM-2",
        )
        response = api.void_claim(claim["id"], {"void_reason_code": "VOID_TEST"}, CLAIMS_EXAMINER)
        validate_error(response, ApiErrorId.ERR_CLAIM_NOT_FINALIZED.value)

        after = get_claim(claim["id"])
        assert after["status"] == "RECEIVED"
        assert after["payment_status"] == "NOT_REMITTED"

    def test_adjudicating_a_duplicate_rejected_claim_returns_invalid_claim_state(self, api):
        """PRD §3.4: "Such a claim never prices, never finalizes and never posts to any
        accumulator; because `DUPLICATE_REJECTED` is excluded from the prior-claim pool, it
        also never seeds a further duplicate of its own."
        PRD §3.5: "A pass may be run from `RECEIVED` or from `PENDED`; attempting one on a
        claim that is `FINALIZED`, `VOIDED`, `ADJUSTED` or `DUPLICATE_REJECTED` is refused
        with `ERR_INVALID_CLAIM_STATE`."

        Design: Corner/state_machines/adjudicate_a_duplicate_rejected_claim_returns_invalid_claim_state
        """
        env = setup_duplicate_pair()
        rejected = env["repeat_claim"]
        assert rejected["status"] == "DUPLICATE_REJECTED"

        response = api.adjudicate_claim(rejected["id"], CLAIMS_EXAMINER)
        validate_error(response, ApiErrorId.ERR_INVALID_CLAIM_STATE.value)

        after = get_claim(rejected["id"])
        assert after["total_allowed_cents"] == 0
        assert after["adjudication_pass"] == 0

    def test_other_payer_posting_on_a_finalized_claim_returns_invalid_claim_state(self, api):
        """PRD §3.7: "The posting is accepted from exactly three claim statuses —
        `RECEIVED`, `PENDED` and `ADJUDICATED` — and from any other status it is refused
        with `ERR_INVALID_CLAIM_STATE`."

        Design: Corner/state_machines/other_payer_payment_on_a_finalized_claim_returns_invalid_claim_state
        """
        env = setup_imaging_environment(
            plan_overrides={"plan_code": "SM-9", "name": "State Machine Plan Nine"},
            provider_overrides={"npi": "2000000014", "name": "SM9 Clinic"},
            member_overrides={"member_number": "M-SM-9"},
            coverages=[OPEN_SECONDARY_COVERAGE],
        )
        adjudicated = submit_and_adjudicate(
            env,
            [claim_line_payload(1, "73721", 1, 60000, "2026-02-10")],
            "CLM-SM-9",
            other_payer_paid_cents=0,
        )
        finalized = finalize(adjudicated["id"])

        response = api.post_other_payer_payment(
            finalized["id"],
            other_payer_payment_payload(5000, finalized["version"]),
            CLAIMS_INTAKE,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_CLAIM_STATE.value)

        claim = get_claim(finalized["id"])
        assert claim["status"] == "FINALIZED"
        assert claim["other_payer_paid_cents"] == 0, (
            "The refused posting must not overwrite the reported figure"
        )
