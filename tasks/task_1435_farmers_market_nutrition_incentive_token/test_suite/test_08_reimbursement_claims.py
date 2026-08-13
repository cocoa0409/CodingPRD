"""Reimbursement claims: dual pricing variants, dispute cycle, gates (PRD §3.6)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_booth_scenario, setup_submitted_claim, setup_approved_claim,
    issue_tokens, redeem_serials, create_submission, close_day,
    verify_submission, decide_submission, run_settlement,
    create_fraud_case_payload,
    make_vendor_headers,
    assert_submission,
)

ADMIN = TEST_USERS["program_admin_headers"]
BOOTH = TEST_USERS["booth_operator_headers"]
MANAGER = TEST_USERS["market_manager_headers"]
AUDITOR = TEST_USERS["auditor_headers"]

_PROVISIONAL_QUOTE = (
    "At creation — and again at every resubmission — the platform records an "
    "optimistic `provisional_amount_cents`: the 2.5 percent administration "
    "withholding is netted against each token line separately, each line's "
    "face value reduced by the withholding and rounded half up to a whole "
    "cent, and the rounded lines are then summed; every token attached at "
    "that moment contributes, whatever happens to its status afterward."
)
_FINAL_QUOTE = (
    "At approval the platform computes the final `approved_amount_cents` with "
    "the opposite order: the face values of the attached tokens still "
    "`REDEEMED` at that instant are summed first, the withholding is applied "
    "once to the aggregate, and the single result is rounded half up to a "
    "whole cent — sum first, withhold once, round once."
)
_DIVERGENCE_QUOTE = (
    "The two variants legitimately diverge on identical token sets: a claim "
    "holding one five-dollar token and two one-dollar tokens prices "
    "provisionally at 684 cents (488 plus 98 plus 98) but finally at 683 (the "
    "700-cent aggregate less 2.5 percent, rounded half up), and they diverge "
    "further when tokens leave `REDEEMED` status before approval."
)


def _setup_700_claim(api):
    """Charge 700 -> base 1x500 (100001) + 2x100 (200001, 200002); vendor
    redeems all three; claim created; day closed; claim VERIFIED."""
    sc = setup_booth_scenario()
    issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 700)
    vend_id = sc["vendor"]["id"]
    t0, t1, t2 = tokens[0], tokens[1], tokens[2]
    assert (t0["serial_number"], t0["denomination_cents"]) == (100001, 500)
    assert (t1["serial_number"], t2["serial_number"]) == (200001, 200002)
    redeem_serials(vend_id, [t0["serial_number"], t1["serial_number"], t2["serial_number"]])
    submission = create_submission(vend_id, sc["market_day"]["id"],
                                   [t0["id"], t1["id"], t2["id"]])
    close_day(sc["market_day"]["id"])
    verify_submission(submission["id"], "VERIFIED")
    sc.update({"issuance": issuance, "tokens": tokens,
               "claimed_tokens": [t0, t1, t2], "submission": submission})
    return sc


class TestDualVariantRounding:
    def test_provisional_per_line_rounding(self, api):
        """PRD §3.6: "At creation — and again at every resubmission — the
        platform records an optimistic `provisional_amount_cents`: the 2.5
        percent administration withholding is netted against each token line
        separately, each line's face value reduced by the withholding and
        rounded half up to a whole cent, and the rounded lines are then summed;
        every token attached at that moment contributes, whatever happens to
        its status afterward."
        PRD §3.6: "The two variants legitimately diverge on identical token
        sets: a claim holding one five-dollar token and two one-dollar tokens
        prices provisionally at 684 cents (488 plus 98 plus 98) but finally at
        683 (the 700-cent aggregate less 2.5 percent, rounded half up), and
        they diverge further when tokens leave `REDEEMED` status before
        approval."

        Design: Difficulty/dual_variant_calc/reimbursement_rounding_order_variants_diverge
        """
        sc = _setup_700_claim(api)
        submission = get_success_data(api.get_submission(sc["submission"]["id"], ADMIN))
        assert_submission(submission)
        assert submission["provisional_amount_cents"] == 684, (
            "per-line: round_half_up(487.5)=488, 98, 98")

    def test_approved_aggregate_rounding_diverges(self, api):
        """PRD §3.6: "At approval the platform computes the final
        `approved_amount_cents` with the opposite order: the face values of the
        attached tokens still `REDEEMED` at that instant are summed first, the
        withholding is applied once to the aggregate, and the single result is
        rounded half up to a whole cent — sum first, withhold once, round
        once."
        PRD §3.6: "The two variants legitimately diverge on identical token
        sets: a claim holding one five-dollar token and two one-dollar tokens
        prices provisionally at 684 cents (488 plus 98 plus 98) but finally at
        683 (the 700-cent aggregate less 2.5 percent, rounded half up), and
        they diverge further when tokens leave `REDEEMED` status before
        approval."

        Design: Difficulty/dual_variant_calc/reimbursement_rounding_order_variants_diverge
        """
        sc = _setup_700_claim(api)
        approved = decide_submission(sc["submission"]["id"], "APPROVED")
        assert approved["approved_amount_cents"] == 683, (
            "aggregate: round_half_up(700*0.975) = round_half_up(682.5)")
        assert approved["provisional_amount_cents"] == 684, "provisional stamped at create is kept"
        assert approved["approved_amount_cents"] != approved["provisional_amount_cents"], (
            "variants diverge by exactly one cent on identical rows")
        for token in sc["claimed_tokens"]:
            settled = get_success_data(api.get_token(token["id"], ADMIN))
            assert settled["status"] == "SETTLED", "approval settles attached REDEEMED tokens"


class TestPerLineVsAggregate:
    def _setup_200_claim(self, api):
        """Charge 200 -> 2x100 base redeemed; claim VERIFIED, day CLOSED."""
        sc = setup_booth_scenario()
        issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 200)
        vend_id = sc["vendor"]["id"]
        t0, t1 = tokens[0], tokens[1]
        redeem_serials(vend_id, [t0["serial_number"], t1["serial_number"]])
        submission = create_submission(vend_id, sc["market_day"]["id"], [t0["id"], t1["id"]])
        close_day(sc["market_day"]["id"])
        verify_submission(submission["id"], "VERIFIED")
        sc.update({"issuance": issuance, "tokens": tokens, "submission": submission})
        return sc

    def test_provisional_per_line_196(self, api):
        """PRD §3.6: "At creation — and again at every resubmission — the
        platform records an optimistic `provisional_amount_cents`: the 2.5
        percent administration withholding is netted against each token line
        separately, each line's face value reduced by the withholding and
        rounded half up to a whole cent, and the rounded lines are then summed;
        every token attached at that moment contributes, whatever happens to
        its status afterward."

        Design: Difficulty/combinatorial_formula/reimbursement_per_line_vs_aggregate_rounding
        """
        sc = self._setup_200_claim(api)
        submission = get_success_data(api.get_submission(sc["submission"]["id"], ADMIN))
        assert submission["provisional_amount_cents"] == 196, "98 + 98 per-line"

    def test_approved_aggregate_195(self, api):
        """PRD §3.6: "At approval the platform computes the final
        `approved_amount_cents` with the opposite order: the face values of the
        attached tokens still `REDEEMED` at that instant are summed first, the
        withholding is applied once to the aggregate, and the single result is
        rounded half up to a whole cent — sum first, withhold once, round
        once."

        Design: Difficulty/combinatorial_formula/reimbursement_per_line_vs_aggregate_rounding
        """
        sc = self._setup_200_claim(api)
        approved = decide_submission(sc["submission"]["id"], "APPROVED")
        assert approved["approved_amount_cents"] == 195, (
            "round_half_up(200*0.975) = round_half_up(195.0) — aggregate rounding")
        assert approved["provisional_amount_cents"] == 196
        assert approved["approved_amount_cents"] != approved["provisional_amount_cents"], (
            "rounding order is observable and pinned per variant")


class TestInclusionVariantOnFlag:
    def _setup_flagged_700_claim(self, api):
        sc = _setup_700_claim(api)
        t0 = sc["claimed_tokens"][0]
        get_success_data(api.create_fraud_case(
            create_fraud_case_payload(reason="suspect token", token_id=t0["id"]), AUDITOR))
        return sc

    def test_flag_excluded_from_final_amount(self, api):
        """PRD §3.6: "At approval the platform computes the final
        `approved_amount_cents` with the opposite order: the face values of the
        attached tokens still `REDEEMED` at that instant are summed first, the
        withholding is applied once to the aggregate, and the single result is
        rounded half up to a whole cent — sum first, withhold once, round
        once."
        PRD §3.6: "The two variants legitimately diverge on identical token
        sets: a claim holding one five-dollar token and two one-dollar tokens
        prices provisionally at 684 cents (488 plus 98 plus 98) but finally at
        683 (the 700-cent aggregate less 2.5 percent, rounded half up), and
        they diverge further when tokens leave `REDEEMED` status before
        approval."

        Design: Difficulty/dual_variant_calc/reimbursement_inclusion_variants_diverge_on_flag
        """
        sc = self._setup_flagged_700_claim(api)
        approved = decide_submission(sc["submission"]["id"], "APPROVED")
        assert approved["provisional_amount_cents"] == 684, "computed at create, unchanged"
        assert approved["approved_amount_cents"] == 195, (
            "flagged 500-cent token excluded: round_half_up(200*0.975)")

    def test_flagged_token_status_after_case_open(self, api):
        """PRD §3.7: "When a case targets a token, opening it immediately moves
        a `REDEEMED` token to `FLAGGED`."
        PRD §3.6: "At approval the platform computes the final
        `approved_amount_cents` with the opposite order: the face values of the
        attached tokens still `REDEEMED` at that instant are summed first, the
        withholding is applied once to the aggregate, and the single result is
        rounded half up to a whole cent — sum first, withhold once, round
        once."

        Design: Difficulty/dual_variant_calc/reimbursement_inclusion_variants_diverge_on_flag
        """
        sc = self._setup_flagged_700_claim(api)
        t0 = sc["claimed_tokens"][0]
        flagged = get_success_data(api.get_token(t0["id"], ADMIN))
        assert flagged["status"] == "FLAGGED", "case open quarantines the token"

        approved = decide_submission(sc["submission"]["id"], "APPROVED")
        assert approved["approved_amount_cents"] == 195, "final input set is REDEEMED-only"
        for token in sc["claimed_tokens"][1:]:
            settled = get_success_data(api.get_token(token["id"], ADMIN))
            assert settled["status"] == "SETTLED", "tokens still REDEEMED settle at approval"


class TestDisputeResubmitCycle:
    def _setup_disputed_claim(self, api):
        """Charge 200 -> 2x100 base redeemed; claim [t0] only; day CLOSED;
        claim DISPUTED."""
        sc = setup_booth_scenario()
        issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 200)
        vend_id = sc["vendor"]["id"]
        t0, t1 = tokens[0], tokens[1]
        redeem_serials(vend_id, [t0["serial_number"], t1["serial_number"]])
        submission = create_submission(vend_id, sc["market_day"]["id"], [t0["id"]])
        close_day(sc["market_day"]["id"])
        verify_submission(submission["id"], "DISPUTED")
        sc.update({"issuance": issuance, "tokens": tokens,
                   "claimed": [t0, t1], "submission": submission})
        return sc

    def test_resubmit_recomputes_provisional(self, api):
        """PRD §3.6: "A disputed claim can be cured by its owning vendor — any
        other actor is refused with `ERR_FORBIDDEN` — by supplying a full
        replacement `token_ids` list, which returns the claim `DISPUTED →
        SUBMITTED`."
        PRD §3.6: "On acceptance the previously attached tokens are detached —
        their `submission_id` cleared — the new tokens are attached,
        `provisional_amount_cents` is recomputed, and the claim's `version`
        increments."

        Design: Difficulty/non_linear_state_machine/submission_dispute_resubmit_cycle_recomputes_provisional
        """
        sc = self._setup_disputed_claim(api)
        vend_id = sc["vendor"]["id"]
        sub = sc["submission"]
        assert sub["provisional_amount_cents"] == 98, "single 100-cent line at create"

        t0, t1 = sc["claimed"]
        resubmitted = validate_success(api.resubmit_submission(
            sub["id"], [t0["id"], t1["id"]], make_vendor_headers(vend_id)))
        assert resubmitted["status"] == "SUBMITTED", "cure returns the claim to SUBMITTED"
        assert resubmitted["id"] == sub["id"], "the claim keeps its identity across the loop"
        assert resubmitted["provisional_amount_cents"] == 196, "recomputed on the replacement list"

    def test_resubmit_cycle_reaches_approval_and_settles(self, api):
        """PRD §3.6: "Approval computes `approved_amount_cents` by the
        aggregate-rounding variant, stamps `approved_at`, moves every attached
        token still `REDEEMED` to `SETTLED`, recomputes the vendor's
        `payable_cents` upward by the approved amount, and recomputes each
        token's market-day totals — because `REDEEMED` and `SETTLED` both count
        toward `redeemed_value_cents`, the day's variance does not move."

        Design: Difficulty/non_linear_state_machine/submission_dispute_resubmit_cycle_recomputes_provisional
        """
        sc = self._setup_disputed_claim(api)
        vend_id = sc["vendor"]["id"]
        sub = sc["submission"]
        t0, t1 = sc["claimed"]
        validate_success(api.resubmit_submission(
            sub["id"], [t0["id"], t1["id"]], make_vendor_headers(vend_id)))
        verify_submission(sub["id"], "VERIFIED")
        approved = decide_submission(sub["id"], "APPROVED")
        assert approved["status"] == "APPROVED"
        assert approved["id"] == sub["id"]
        assert approved["approved_amount_cents"] == 195, "aggregate rounding on 200"
        for token in (t0, t1):
            settled = get_success_data(api.get_token(token["id"], ADMIN))
            assert settled["status"] == "SETTLED"


class TestVerificationGate:
    def _setup_open_day_claim(self, api):
        sc = setup_booth_scenario()
        issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 300)
        vend_id = sc["vendor"]["id"]
        t0 = tokens[0]
        redeem_serials(vend_id, [t0["serial_number"]])
        submission = create_submission(vend_id, sc["market_day"]["id"], [t0["id"]])
        sc.update({"issuance": issuance, "tokens": tokens, "submission": submission})
        return sc

    def test_verify_on_open_day_rejected(self, api):
        """PRD §3.6: "Verification requires the claim's market day to be
        `CLOSED` or `VARIANCE_FLAGGED` — a day in any earlier state rejects the
        attempt with `ERR_MARKET_DAY_NOT_CLOSED`."

        Design: Difficulty/cross_entity_state_dependency/submission_verify_gated_by_day_closed
        """
        sc = self._setup_open_day_claim(api)
        resp = api.verify_submission(sc["submission"]["id"], "VERIFIED", MANAGER)
        validate_error(resp, ApiErrorId.ERR_MARKET_DAY_NOT_CLOSED)

    def test_verify_on_open_day_leaves_submission_submitted(self, api):
        """PRD §3.6: "Verification requires the claim's market day to be
        `CLOSED` or `VARIANCE_FLAGGED` — a day in any earlier state rejects the
        attempt with `ERR_MARKET_DAY_NOT_CLOSED`."
        PRD §3.6: "On acceptance each listed token's `submission_id` is set to
        the new claim and the claim starts in `SUBMITTED` status."

        Design: Difficulty/cross_entity_state_dependency/submission_verify_gated_by_day_closed
        """
        sc = self._setup_open_day_claim(api)
        resp = api.verify_submission(sc["submission"]["id"], "VERIFIED", MANAGER)
        validate_error(resp, ApiErrorId.ERR_MARKET_DAY_NOT_CLOSED)

        submission = get_success_data(api.get_submission(sc["submission"]["id"], ADMIN))
        assert submission["status"] == "SUBMITTED", "rejected verify leaves the claim untouched"
        assert submission["version"] == sc["submission"]["version"]


class TestClaimShapeAndAttachment:
    def test_empty_token_ids_rejected(self, api):
        """PRD §3.6: "An empty `token_ids` array is rejected with
        `ERR_SUBMISSION_EMPTY`."

        Design: Corner/validations/c_val_empty_token_ids_rejected
        """
        sc = setup_booth_scenario()
        resp = api.create_submission(
            {"market_day_id": sc["market_day"]["id"], "token_ids": []},
            make_vendor_headers(sc["vendor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SUBMISSION_EMPTY)

    def test_token_already_attached_rejected(self, api):
        """PRD §3.6: "Each listed token then passes the strict attachment
        ladder used everywhere tokens are claimed: the token must exist
        (`ERR_REFERENCE_NOT_FOUND`), must not be `FLAGGED` (`ERR_TOKEN_FLAGGED`
        — quarantine outranks even an expired submission window), must have
        been redeemed by the submitting vendor (`ERR_TOKEN_VENDOR_MISMATCH`),
        and must not already be attached to another claim still in a
        non-terminal status — `SUBMITTED`, `VERIFIED`, `DISPUTED`, or
        `APPROVED` (`ERR_TOKEN_ALREADY_SUBMITTED`)."

        Design: Corner/validations/c_val_token_already_attached_to_open_submission_rejected
        """
        sc = setup_submitted_claim(charge=100, redeem_count=1)
        vend_id = sc["vendor"]["id"]
        t0 = sc["claimed_tokens"][0]

        resp = api.create_submission(
            {"market_day_id": sc["market_day"]["id"], "token_ids": [t0["id"]]},
            make_vendor_headers(vend_id))
        validate_error(resp, ApiErrorId.ERR_TOKEN_ALREADY_SUBMITTED)

        subs, meta = validate_paginated(
            api.list_submissions(ADMIN, params={"vendor_id": vend_id}))
        assert meta["total_count"] == 1, "second submission not created"


class TestTerminalClaims:
    def test_paid_submission_rejects_further_decide(self, api):
        """PRD §3.6: "`REJECTED` and `PAID` are the claim's terminal states."
        PRD §2.10: "State gates come next: first the generic rule that any
        transition attempted from a state that does not permit it is rejected
        with `ERR_INVALID_STATE`, then the specific gates in their relative
        order — shopper eligibility (`ERR_SHOPPER_NOT_ELIGIBLE`), vendor
        standing (`ERR_VENDOR_NOT_ACTIVE`), market-day openness
        (`ERR_MARKET_DAY_NOT_OPEN`), and market-day closedness
        (`ERR_MARKET_DAY_NOT_CLOSED`)."

        Design: Corner/state_machines/c_sm_paid_submission_rejects_further_decide
        """
        sc = setup_approved_claim(charge=200, token_count=2)
        run_settlement(sc["program"]["id"])
        submission = get_success_data(api.get_submission(sc["submission"]["id"], ADMIN))
        assert submission["status"] == "PAID"
        assert submission["paid_amount_cents"] == 195

        resp = api.decide_submission(sc["submission"]["id"], "REJECTED", ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = get_success_data(api.get_submission(sc["submission"]["id"], ADMIN))
        assert after["status"] == "PAID", "PAID is terminal"
        assert after["paid_amount_cents"] == 195, "paid amount unchanged"


class TestSegregationOfDuties:
    def test_booth_operator_cannot_decide_submission(self, api):
        """PRD §3.6: "Adjudication belongs to the `ProgramAdmin`; verification
        and approval are deliberately segregated between the two roles, so no
        single operator can both verify and approve a claim."
        PRD §2.1: "An attempt to perform an operation outside the caller's
        designated role is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/c_rbac_booth_operator_cannot_decide_submission
        """
        sc = setup_submitted_claim(charge=100, redeem_count=1)
        close_day(sc["market_day"]["id"])
        verify_submission(sc["submission"]["id"], "VERIFIED")

        resp = api.decide_submission(sc["submission"]["id"], "APPROVED", BOOTH)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        submission = get_success_data(api.get_submission(sc["submission"]["id"], ADMIN))
        assert submission["status"] == "VERIFIED", "refused decide leaves the claim VERIFIED"

    def test_vendor_cannot_verify_own_submission(self, api):
        """PRD §2.1: "`Vendor` — a market vendor: redeems tokens by serial
        number, reverses its own redemptions, and submits or resubmits
        reimbursement claims. A vendor can never verify or approve its own
        claims."
        PRD §3.6: "Verification belongs to the `MarketManager` and moves a
        `SUBMITTED` claim to either `VERIFIED` or `DISPUTED` according to the
        supplied `outcome`."
        PRD §2.1: "An attempt to perform an operation outside the caller's
        designated role is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/c_rbac_vendor_cannot_verify_own_submission
        """
        sc = setup_submitted_claim(charge=100, redeem_count=1)
        close_day(sc["market_day"]["id"])

        resp = api.verify_submission(sc["submission"]["id"], "VERIFIED",
                                     make_vendor_headers(sc["vendor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        submission = get_success_data(api.get_submission(sc["submission"]["id"], ADMIN))
        assert submission["status"] == "SUBMITTED"
