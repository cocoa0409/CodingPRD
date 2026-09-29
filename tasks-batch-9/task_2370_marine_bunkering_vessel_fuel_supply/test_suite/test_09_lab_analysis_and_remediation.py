"""Laboratory testing, the off-spec verdict, the retest cycle and the credit.

A quality claim negotiates: the laboratory files, the surveyor proposes, the buyer
may push back once, the laboratory files again and only then does a credit stick.
The verdict that drives all of it turns on a trip point that is inclusive at the
boundary, and accepting the eventual proposal moves money three records deep.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    CREDIT_USER_ID,
    SURVEYOR_USER_ID,
    api_client,
    assert_lab_analysis,
    assert_quality_claim,
    build_issued_invoice,
    build_proposed_claim,
    build_submitted_claim,
    accept_remediation,
    claim_decision_payload,
    file_lab_analysis,
    force_credit_hold,
    make_customer_rep_headers,
    make_surveyor_headers,
    raise_claim,
    read_claim,
    read_customer,
    read_invoice,
    request_retest,
    submit_claim_decision,
    validate_error,
)


class TestRemediationRetestCycle:
    """`UNDER_ANALYSIS → REMEDIATION_PROPOSED → UNDER_ANALYSIS`, then a hard stop."""

    def test_first_round_verdict_drives_the_price_allowance_credit(self):
        """PRD §3.8: "The first filing on a claim moves it `SUBMITTED →
        UNDER_ANALYSIS`, sets the analysis's `round_index` to 1 and the claim's
        `analysis_round` to 1, and increments the claim's `version` by one."
        PRD §3.8: "Fourth, a per-tonne rate is derived from the remediation branch:
        on the `PRICE_ALLOWANCE` branch it is the reference price multiplied by an
        off-spec allowance of 15 percent, rounded to two decimal places"
        PRD §3.8: "Fifth, the raw credit is the affected tonnage multiplied by that
        rate, rounded to two decimal places."
        PRD §3.8: "Eighth, `credit_usd` is the lesser of the raw credit and that
        cap."

        A reference price of 745.50 gives a rate of 111.83 per tonne, so 400.000
        affected tonnes earn 44732.00, comfortably under the 564716.24 cap.

        Design: Difficulty/non_linear_state_machine/quality_claim_remediation_retest_cycle
        """
        ctx = build_submitted_claim()

        analysis = file_lab_analysis(ctx, measured_sulfur_pct=0.135)

        assert_lab_analysis(analysis)
        assert analysis["round_index"] == 1, (
            f"A first filing is round one, got {analysis['round_index']}"
        )
        assert analysis["verdict"] == "OFF_SPEC", (
            f"0.135 clears the 0.110 trip point, got {analysis['verdict']}"
        )
        assert analysis["exceedance_pct"] == pytest.approx(0.025, abs=0.0005), (
            f"0.135 less the 0.110 trip point is 0.025, got "
            f"{analysis['exceedance_pct']}"
        )
        claim = read_claim(ctx)
        assert claim["status"] == "UNDER_ANALYSIS", (
            f"The first filing opens the analysis phase, got {claim['status']}"
        )
        assert claim["analysis_round"] == 1, (
            f"Expected analysis_round 1, got {claim['analysis_round']}"
        )

        proposed = submit_claim_decision(ctx, "PROPOSE")

        assert_quality_claim(proposed)
        assert proposed["status"] == "REMEDIATION_PROPOSED", (
            f"An off-spec finding permits a proposal, got {proposed['status']}"
        )
        assert proposed["credit_usd"] == pytest.approx(44732.00, abs=0.01), (
            "400.000 tonnes at 111.83 per tonne is 44732.00, got "
            f"{proposed['credit_usd']}"
        )
        assert proposed["proposed_by_user_id"] == SURVEYOR_USER_ID, (
            "The proposing surveyor must be recorded, got "
            f"{proposed['proposed_by_user_id']}"
        )

    def test_retest_request_rewinds_the_proposal_and_the_second_round_escalates(self):
        """PRD §3.8: "Requesting a retest moves the claim `REMEDIATION_PROPOSED →
        UNDER_ANALYSIS`, clears `remediation_type` to null, resets `credit_usd` to
        0.00, clears `proposed_by_user_id` to null and increments the claim's
        `version` by one"
        PRD §3.8: "It sets the new analysis's `round_index` to 2 and the claim's
        `analysis_round` to 2 and increments the claim's `version` by one."
        PRD §3.8: "Sixth, severity is escalated: if the governing analysis's
        `exceedance_pct` is strictly greater than 0.050 mass percent, the raw credit
        is multiplied by 1.25 and rounded again to two decimal places."

        Design: Difficulty/non_linear_state_machine/quality_claim_remediation_retest_cycle
        """
        ctx = build_proposed_claim()
        first_analysis = ctx["analysis"]

        rewound = request_retest(ctx)

        assert rewound["status"] == "UNDER_ANALYSIS", (
            f"The claim returns to the analysis phase, got {rewound['status']}"
        )
        assert rewound["credit_usd"] == pytest.approx(0.00, abs=0.01), (
            f"The proposed credit must be reset, got {rewound['credit_usd']}"
        )
        assert rewound["remediation_type"] is None, (
            f"The remediation branch must be cleared, got {rewound['remediation_type']}"
        )
        assert rewound["proposed_by_user_id"] is None, (
            f"The proposer must be cleared, got {rewound['proposed_by_user_id']}"
        )

        second = file_lab_analysis(
            ctx,
            lab_ref="LAB-0002",
            measured_sulfur_pct=0.200,
            retest_of_analysis_id=first_analysis["id"],
        )

        assert second["round_index"] == 2, (
            f"A retest is round two, got {second['round_index']}"
        )
        assert second["retest_of_analysis_id"] == first_analysis["id"], (
            "The retest must name the round-one analysis, got "
            f"{second['retest_of_analysis_id']}"
        )
        assert second["exceedance_pct"] == pytest.approx(0.090, abs=0.0005), (
            f"0.200 less the 0.110 trip point is 0.090, got "
            f"{second['exceedance_pct']}"
        )
        assert read_claim(ctx)["analysis_round"] == 2, (
            "The claim must record the second round"
        )

        reproposed = submit_claim_decision(ctx, "PROPOSE")

        assert reproposed["credit_usd"] == pytest.approx(55915.00, abs=0.01), (
            "An exceedance above 0.050 lifts 44732.00 by the 1.25 multiplier to "
            f"55915.00, got {reproposed['credit_usd']}"
        )

    def test_a_second_pushback_is_refused_at_the_two_round_ceiling(self):
        """PRD §3.8: "A third filing has nowhere to go and is rejected with
        `ERR_RETEST_LIMIT_REACHED` (HTTP 409); the same ceiling and the same error
        also govern a customer's request for a retest."

        Design: Difficulty/non_linear_state_machine/quality_claim_remediation_retest_cycle
        """
        ctx = build_proposed_claim()
        first_analysis = ctx["analysis"]
        request_retest(ctx)
        file_lab_analysis(
            ctx,
            lab_ref="LAB-0002",
            measured_sulfur_pct=0.200,
            retest_of_analysis_id=first_analysis["id"],
        )
        submit_claim_decision(ctx, "PROPOSE")

        response = api_client.request_retest(
            ctx["claim"]["id"], make_customer_rep_headers(ctx["customer"]["id"])
        )

        validate_error(response, ApiErrorId.ERR_RETEST_LIMIT_REACHED)
        claim = read_claim(ctx)
        assert claim["status"] == "REMEDIATION_PROPOSED", (
            "The refused pushback must leave the proposal standing, got "
            f"{claim['status']}"
        )
        assert claim["analysis_round"] == 2, (
            f"The round count must stay at the ceiling, got {claim['analysis_round']}"
        )


class TestOffSpecTripPoint:
    """The tolerance boundary is inclusive, so the trip point itself is on-spec."""

    def _two_claims_on_one_note(self):
        """Two claims against the same issued note: 400.000 mt and 100.000 mt."""
        ctx = build_submitted_claim()
        claim_p = ctx["claim"]
        claim_q = raise_claim(ctx, affected_quantity_mt=100.000)
        return ctx, claim_p, claim_q

    def test_measurement_exactly_at_the_trip_point_is_on_spec(self):
        """PRD §3.8: "The regulatory limit that applies is the port's
        `eca_sulfur_limit_pct` when the delivery port lies inside an Emission Control
        Area and the receiving vessel has no scrubber fitted; in every other case it
        is the grade's `max_sulfur_pct`."
        PRD §3.8: "The trip point is the effective limit plus the grade's
        `test_tolerance_pct`, the ISO 4259 reproducibility allowance."
        PRD §3.8: "The `verdict` is `OFF_SPEC` when `measured_sulfur_pct` is strictly
        greater than that trip point and `ON_SPEC` otherwise — a measurement exactly
        equal to the trip point is `ON_SPEC`."
        PRD §3.8: "`exceedance_pct` is `measured_sulfur_pct` minus the trip point,
        rounded to three decimal places, and floored at 0.000, so an on-spec result
        always reports an exceedance of 0.000."

        The effective limit is 0.100 and the tolerance 0.010, so the trip point is
        0.110: a reading of 0.110 is on-spec and 0.111 is off-spec by 0.001.

        Design: Difficulty/boundary_precision_check/sulfur_offspec_at_exact_tolerance_boundary
        """
        ctx, claim_p, claim_q = self._two_claims_on_one_note()

        at_the_point = file_lab_analysis(
            ctx, claim_id=claim_p["id"], lab_ref="LAB-BOUND-110",
            measured_sulfur_pct=0.110,
        )
        one_step_over = file_lab_analysis(
            ctx, claim_id=claim_q["id"], lab_ref="LAB-BOUND-111",
            measured_sulfur_pct=0.111,
        )

        assert at_the_point["verdict"] == "ON_SPEC", (
            "A reading exactly equal to the 0.110 trip point is on-spec, got "
            f"{at_the_point['verdict']}"
        )
        assert at_the_point["exceedance_pct"] == pytest.approx(0.000, abs=0.0005), (
            "An on-spec result reports no exceedance, got "
            f"{at_the_point['exceedance_pct']}"
        )
        assert one_step_over["verdict"] == "OFF_SPEC", (
            "0.111 is strictly greater than the trip point, got "
            f"{one_step_over['verdict']}"
        )
        assert one_step_over["exceedance_pct"] == pytest.approx(0.001, abs=0.0005), (
            f"0.111 less 0.110 is 0.001, got {one_step_over['exceedance_pct']}"
        )

    def test_first_round_analyses_carry_round_one_and_no_retest_link(self):
        """PRD §3.8: "A retest additionally carries `retest_of_analysis_id`, naming
        the first-round analysis being re-examined; on a first round it is omitted and
        defaults to null."

        Design: Difficulty/boundary_precision_check/sulfur_offspec_at_exact_tolerance_boundary
        """
        ctx, claim_p, claim_q = self._two_claims_on_one_note()

        first = file_lab_analysis(
            ctx, claim_id=claim_p["id"], lab_ref="LAB-BOUND-110",
            measured_sulfur_pct=0.110,
        )
        second = file_lab_analysis(
            ctx, claim_id=claim_q["id"], lab_ref="LAB-BOUND-111",
            measured_sulfur_pct=0.111,
        )

        for analysis in (first, second):
            assert analysis["round_index"] == 1, (
                f"A first filing is round one, got {analysis['round_index']}"
            )
            assert analysis["retest_of_analysis_id"] is None, (
                "A first-round filing carries no retest link, got "
                f"{analysis['retest_of_analysis_id']}"
            )

    def test_proposal_is_refused_when_the_governing_verdict_is_on_spec(self):
        """PRD §3.8: "Proposing moves the claim `UNDER_ANALYSIS →
        REMEDIATION_PROPOSED` and requires the governing analysis to have verdict
        `OFF_SPEC`; rejecting moves the claim `UNDER_ANALYSIS → REJECTED` and requires
        the governing analysis to have verdict `ON_SPEC`. A decision that contradicts
        the governing verdict in either direction is rejected with
        `ERR_NO_OFFSPEC_FINDING` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/sulfur_offspec_at_exact_tolerance_boundary
        """
        ctx, claim_p, _claim_q = self._two_claims_on_one_note()
        file_lab_analysis(
            ctx, claim_id=claim_p["id"], lab_ref="LAB-BOUND-110",
            measured_sulfur_pct=0.110,
        )

        response = api_client.claim_decision(
            claim_p["id"],
            claim_decision_payload("PROPOSE"),
            make_surveyor_headers(SURVEYOR_USER_ID),
        )

        validate_error(response, ApiErrorId.ERR_NO_OFFSPEC_FINDING)
        claim = read_claim(claim_id=claim_p["id"])
        assert claim["status"] == "UNDER_ANALYSIS", (
            f"The refused proposal must leave the claim under analysis, got "
            f"{claim['status']}"
        )
        assert claim["credit_usd"] == pytest.approx(0.00, abs=0.01), (
            f"No credit may be computed on an on-spec finding, got "
            f"{claim['credit_usd']}"
        )


class TestCreditBookingCascade:
    """Acceptance moves claim, invoice and buyer standing in one request."""

    def _proposed_claim_on_a_held_buyer(self):
        """An issued 941193.73 invoice, a limit shrunk to match it, and a proposal."""
        ctx = build_issued_invoice()
        force_credit_hold(ctx)
        return build_proposed_claim(ctx)

    def test_acceptance_cascades_three_levels_deep(self):
        """PRD §3.8: "The credit desk accepts a proposed remediation, moving the claim
        `REMEDIATION_PROPOSED → REMEDIATION_ACCEPTED` and recording the acting
        `X-User-ID` as `accepted_by_user_id`, which must differ from
        `proposed_by_user_id` per the segregation rule of §2.1."
        PRD §3.8: "Acceptance books `credit_usd` and cascades three levels deep: the
        invoice's `claim_credit_usd` is increased by the claim's `credit_usd`, its
        `final_amount_usd` is recomputed, and its `status` moves `ISSUED →
        CREDIT_APPLIED`; that invoice mutation itself cascades a recompute of the
        customer's `outstanding_balance_usd`; and that recompute in turn cascades a
        re-derivation of the customer's `credit_status`."

        Design: Difficulty/transitive_cascade/claim_acceptance_credit_cascade_depth_three
        """
        ctx = self._proposed_claim_on_a_held_buyer()
        before = read_customer(ctx)
        assert before["outstanding_balance_usd"] == pytest.approx(941193.73, abs=0.01), (
            f"The issued invoice is the whole receivable, got "
            f"{before['outstanding_balance_usd']}"
        )
        assert before["credit_status"] == "HOLD", (
            f"Utilisation of exactly 1.0000 is a hold, got {before['credit_status']}"
        )

        claim = accept_remediation(ctx)

        assert claim["status"] == "REMEDIATION_ACCEPTED", (
            f"Level one: the claim must settle, got {claim['status']}"
        )
        assert claim["credit_usd"] == pytest.approx(44732.00, abs=0.01), (
            f"The booked credit must be 44732.00, got {claim['credit_usd']}"
        )
        assert claim["accepted_by_user_id"] == CREDIT_USER_ID, (
            f"The accepting controller must be recorded, got "
            f"{claim['accepted_by_user_id']}"
        )

        invoice = read_invoice(ctx)
        assert invoice["status"] == "CREDIT_APPLIED", (
            f"Level two: the invoice must absorb the credit, got {invoice['status']}"
        )
        assert invoice["claim_credit_usd"] == pytest.approx(44732.00, abs=0.01), (
            f"Expected 44732.00 booked against the invoice, got "
            f"{invoice['claim_credit_usd']}"
        )

        customer = read_customer(ctx)
        assert customer["outstanding_balance_usd"] == pytest.approx(896461.73, abs=0.01), (
            "Level three: the receivable must fall to the net figure, got "
            f"{customer['outstanding_balance_usd']}"
        )
        assert customer["credit_status"] == "WATCH", (
            "Utilisation of 0.9525 sits between 0.8000 and 1.0000, so the hold must "
            f"lift to a watch, got {customer['credit_status']}"
        )

    def test_provisional_total_survives_the_credit_untouched(self):
        """PRD §3.9: "`final_amount_usd` is `provisional_amount_usd` minus
        `claim_credit_usd`, rounded to two decimal places."
        PRD §3.9: "`provisional_amount_usd` is the sum of those four rounded
        components."

        The credit lands on `claim_credit_usd` and `final_amount_usd` only; the
        component total the invoice was raised on is not rewritten.

        Design: Difficulty/transitive_cascade/claim_acceptance_credit_cascade_depth_three
        """
        ctx = self._proposed_claim_on_a_held_buyer()

        accept_remediation(ctx)

        invoice = read_invoice(ctx)
        assert invoice["provisional_amount_usd"] == pytest.approx(941193.73, abs=0.001), (
            "The component total must be preserved, got "
            f"{invoice['provisional_amount_usd']}"
        )
        assert invoice["final_amount_usd"] == pytest.approx(896461.73, abs=0.001), (
            "941193.73 less the 44732.00 credit is 896461.73, got "
            f"{invoice['final_amount_usd']}"
        )
