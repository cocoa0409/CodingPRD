"""Charge statements, line postings, protest evidence scoring, protest
adjudication cascades, withdrawal/waive compensation, and statement OCC."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    ack_claim,
    create_claim,
    create_employer,
    create_separation,
    create_state_rule,
    create_statement,
    determine_claim,
    file_protest,
    get_claim,
    get_employer,
    get_line_item,
    get_protest,
    get_separation,
    get_statement,
    post_line,
    review_protest,
    set_clock,
    setup_statement_with_line,
    setup_under_adjudication_claim,
    submit_response,
    draft_response,
    attach_evidence,
    sustain_protest,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["claims_analyst_headers"]
LIAISON = TEST_USERS["agency_liaison_headers"]
AUDITOR = TEST_USERS["charge_auditor_headers"]


class TestMaxBenefitCapBoundary:
    def test_charge_line_at_exact_max_benefit_cap(self, api):
        """PRD §3.6: "One fiscal cap guards the posting: the claim's
        `charged_amount_cents` may not be pushed above its `max_benefit_cents`
        (otherwise `ERR_MAX_BENEFIT_EXCEEDED`)."

        Design: Difficulty/boundary_precision_check/charge_line_at_exact_max_benefit_cap
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        ctx = setup_statement_with_line(amount_cents=1_000_000,
                                        erroneous_reason=None,
                                        max_benefit_cents=1_000_000)
        # Landing exactly on the cap is permitted ("pushed above" is the cap).
        assert ctx["line"]["status"] == "PENDING"
        assert get_claim(ctx["claim"]["id"])["charged_amount_cents"] == 1_000_000

        err = api.post_line_item(ctx["statement"]["id"],
                                 {"claim_id": ctx["claim"]["id"],
                                  "amount_cents": 1, "benefit_weeks": 1},
                                 LIAISON)
        validate_error(err, ApiErrorId.ERR_MAX_BENEFIT_EXCEEDED, 422)
        assert get_claim(ctx["claim"]["id"])["charged_amount_cents"] == 1_000_000
        assert get_line_item(ctx["line"]["id"])["status"] == "PENDING"

    def test_cumulative_lines_reach_cap_inclusively(self, api):
        """PRD §3.6: "Posting a line moves three ledgers at once: the
        statement's `total_charged_cents` increases by the amount, the claim's
        `charged_amount_cents` increases by the amount, and the employer's
        `reserve_balance_cents` decreases by the amount — the reserve is
        debited when the charge posts."

        Design: Difficulty/boundary_precision_check/charge_line_at_exact_max_benefit_cap
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        ctx = setup_statement_with_line(amount_cents=600_000,
                                        erroneous_reason=None,
                                        max_benefit_cents=1_000_000)
        line2 = post_line(ctx["statement"]["id"], ctx["claim"]["id"], 400_000,
                          benefit_weeks=10)
        assert line2["status"] == "PENDING"
        assert get_claim(ctx["claim"]["id"])["charged_amount_cents"] == 1_000_000
        assert get_statement(ctx["statement"]["id"])["total_charged_cents"] == 1_000_000

        err = api.post_line_item(ctx["statement"]["id"],
                                 {"claim_id": ctx["claim"]["id"],
                                  "amount_cents": 1, "benefit_weeks": 1},
                                 LIAISON)
        validate_error(err, ApiErrorId.ERR_MAX_BENEFIT_EXCEEDED, 422)


class TestProtestEvidenceScore:
    def _setup_denied_claim_with_coding_confirmed(self, api):
        """Claim answered ON_TIME and ACCEPTED; coding CONFIRMED; determination
        DENIED; statement with a WRONG_EMPLOYER line of 500,000 cents."""
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        employer = create_employer(legal_name="OrdCo")
        separation = create_separation(employer["id"], claimant_name="Eve",
                                       ssn_last4="5001")
        claim = create_claim(employer["id"], separation["id"])
        # LAYOFF coding needs no evidence gate; confirm before filing.
        validate_success(api.confirm_coding(separation["id"], ANALYST), 200)
        resp = draft_response(claim["id"], response_type="PROTEST",
                              narrative="Not our former employee's charge.")
        attach_evidence(claim["id"], resp["id"])
        submit_response(claim["id"], resp["id"])
        validate_success(api.accept_response(claim["id"], resp["id"], LIAISON), 200)
        ack_claim(claim["id"])
        determine_claim(claim["id"], outcome="DENIED",
                        mailed_at="2026-08-04T09:00:00Z")
        statement = create_statement(employer["id"], issued_at="2026-08-05T09:00:00Z")
        line = post_line(statement["id"], claim["id"], 500_000, benefit_weeks=4,
                         erroneous_reason="WRONG_EMPLOYER")
        return {"employer": employer, "separation": separation, "claim": claim,
                "statement": statement, "line": line}

    def test_score_sums_in_pinned_order_to_100(self, api):
        """PRD §3.6: "The score starts from the basis weight: 50 for
        `CLAIMANT_NOT_SEPARATED`, 70 for `WRONG_EMPLOYER`, 30 for
        `ALREADY_PROTESTED`, 60 for `EXCEEDS_MAX_BENEFIT`, and 65 for
        `DUPLICATE_LINE`. If the claim has any determination with outcome
        `DENIED` — the agency has already sided with the employer once — the
        score gains 20."
        PRD §3.6: "Then the separation's coding confidence applies: `CONFIRMED`
        adds 10 and `DISPUTED` subtracts 10. The result is clamped into the
        range from zero to one hundred and stored as `evidence_strength`."

        Design: Difficulty/combinatorial_formula/protest_score_evaluation_order_fixed
        """
        ctx = self._setup_denied_claim_with_coding_confirmed(api)
        protest = file_protest(ctx["line"]["id"], ctx["statement"]["id"],
                               protest_basis="WRONG_EMPLOYER")
        # 70 basis + 20 DENIED determination + 0 (latest response ON_TIME)
        # + 10 CONFIRMED coding = 100.
        assert protest["evidence_strength"] == 100
        assert protest["timeliness"] == "ON_TIME"
        assert protest["status"] == "FILED"

    def test_no_submitted_response_means_no_timeliness_term(self, api):
        """PRD §3.6: "if that response exists and its `timeliness` is `LATE`,
        the score loses 25, and if no such response exists no timeliness term
        applies at all."

        Design: Difficulty/combinatorial_formula/protest_score_evaluation_order_fixed
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        ctx = setup_statement_with_line(amount_cents=500_000,
                                        erroneous_reason="WRONG_EMPLOYER")
        # The claim has no response at all; coding is UNREVIEWED.
        protest = file_protest(ctx["line"]["id"], ctx["statement"]["id"],
                               protest_basis="WRONG_EMPLOYER")
        # 70 basis only: no DENIED determination, no response term, UNREVIEWED.
        assert protest["evidence_strength"] == 70

    def test_protest_evidence_below_threshold_cannot_sustain(self, api):
        """PRD §3.6: "if that response exists and its `timeliness` is `LATE`,
        the score loses 25"
        PRD §3.6: "Sustaining requires the protest to be `UNDER_REVIEW` with an
        `evidence_strength` of at least 60 (otherwise
        `ERR_PROTEST_EVIDENCE_WEAK`)"
        PRD §3.4: "Rejection moves the response to `REJECTED_INSUFFICIENT` and
        challenges the employer's coding by setting the separation's confidence
        to `DISPUTED`."

        Design: Corner/calculations/protest_evidence_below_threshold_cannot_sustain
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX", response_window_days=5, window_basis="CALENDAR",
                          weekend_shift="NONE")
        employer = create_employer(legal_name="WeakCo")
        separation = create_separation(employer["id"], claimant_name="Rex",
                                       ssn_last4="1016")
        claim = create_claim(employer["id"], separation["id"])
        resp = draft_response(claim["id"], response_type="PROTEST", narrative="n")
        attach_evidence(claim["id"], resp["id"])
        set_clock("2026-08-09T18:00:00Z")  # past the 5-day deadline
        submitted = submit_response(claim["id"], resp["id"])
        assert submitted["timeliness"] == "LATE"
        validate_success(api.reject_response(claim["id"], resp["id"], LIAISON), 200)
        assert get_separation(separation["id"])["reason_coding_confidence"] == "DISPUTED"

        statement = create_statement(employer["id"], issued_at="2026-08-10T09:00:00Z")
        line = post_line(statement["id"], claim["id"], 300_000, benefit_weeks=3,
                         erroneous_reason="CLAIMANT_NOT_SEPARATED")
        protest = file_protest(line["id"], statement["id"],
                               protest_basis="CLAIMANT_NOT_SEPARATED")
        # 50 basis - 25 LATE latest response - 10 DISPUTED coding = 15.
        assert protest["evidence_strength"] == 15

        review_protest(protest["id"])
        err = api.sustain_protest(protest["id"], LIAISON)
        validate_error(err, ApiErrorId.ERR_PROTEST_EVIDENCE_WEAK, 422)
        assert get_protest(protest["id"])["status"] == "UNDER_REVIEW"
        assert get_separation(separation["id"])["reason_coding_confidence"] == "DISPUTED"


class TestAuditVarianceAndBubbleUp:
    def test_reversed_line_excluded_from_statement_total(self, api):
        """PRD §3.6: "the protest becomes `SUSTAINED` and the line becomes
        `REVERSED`, running the full reversal cascade — statement total and
        claim charged amount each decremented by the line's amount, employer
        reserve credited by the same."
        PRD §3.6: "The same recomputation synchronizes the statement's
        `total_charged_cents` to the audited total, so reversed and waived
        lines never linger in the ledger."

        Design: Corner/calculations/charge_audit_variance_reversed_excluded
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        employer = create_employer(legal_name="VarCo")
        separation = create_separation(employer["id"])
        claim = create_claim(employer["id"], separation["id"],
                             max_benefit_cents=2_000_000)
        statement = create_statement(employer["id"])
        post_line(statement["id"], claim["id"], 400_000, benefit_weeks=4)
        line2 = post_line(statement["id"], claim["id"], 500_000, benefit_weeks=5,
                          erroneous_reason="DUPLICATE_LINE")
        assert get_statement(statement["id"])["total_charged_cents"] == 900_000

        protest = file_protest(line2["id"], statement["id"],
                               protest_basis="DUPLICATE_LINE")
        assert protest["evidence_strength"] == 65
        review_protest(protest["id"])
        sustain_protest(protest["id"])

        assert get_line_item(line2["id"])["status"] == "REVERSED"
        assert get_statement(statement["id"])["total_charged_cents"] == 400_000
        assert get_claim(claim["id"])["charged_amount_cents"] == 400_000

    def test_protest_filing_bubbles_statement_to_under_audit(self, api):
        """PRD §3.6: "A filed protest opens in `FILED` with `filed_at` stamped
        and `timeliness` computed, the line moves from `PENDING` to
        `PROTESTED`, the protest's `evidence_strength` is computed, and a
        statement still in `ISSUED` bubbles up to `UNDER_AUDIT` automatically."

        Design: Corner/endpoints/protest_filing_bubbles_statement_to_under_audit
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        ctx = setup_statement_with_line(amount_cents=100_000,
                                        erroneous_reason="WRONG_EMPLOYER")
        assert ctx["statement"]["status"] == "ISSUED"

        protest = file_protest(ctx["line"]["id"], ctx["statement"]["id"],
                               protest_basis="WRONG_EMPLOYER")
        assert protest["status"] == "FILED"
        assert get_statement(ctx["statement"]["id"])["status"] == "UNDER_AUDIT"
        assert get_line_item(ctx["line"]["id"])["status"] == "PROTESTED"


class TestProtestWithdrawalCompensation:
    def test_withdrawal_from_filed_restores_line_and_totals(self, api):
        """PRD §3.6: "A `ChargeAuditor` may withdraw a protest from `FILED` or
        `UNDER_REVIEW`; the protest becomes `WITHDRAWN` and the line returns to
        `PENDING`, a compensating action restoring the pre-protest ledger
        posture."

        Design: Difficulty/compensating_invariant/protest_withdrawal_restores_line_and_totals
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        ctx = setup_statement_with_line(amount_cents=400_000,
                                        erroneous_reason="WRONG_EMPLOYER")
        protest = file_protest(ctx["line"]["id"], ctx["statement"]["id"],
                               protest_basis="WRONG_EMPLOYER")

        withdrawn = validate_success(api.withdraw_protest(protest["id"], AUDITOR), 200)
        assert withdrawn["status"] == "WITHDRAWN"
        assert get_line_item(ctx["line"]["id"])["status"] == "PENDING"
        # Zero drift in the conserved totals.
        assert get_statement(ctx["statement"]["id"])["total_charged_cents"] == 400_000
        assert get_claim(ctx["claim"]["id"])["charged_amount_cents"] == 400_000

    def test_withdrawal_from_under_review_restores_line(self, api):
        """PRD §3.6: "A `ChargeAuditor` may withdraw a protest from `FILED` or
        `UNDER_REVIEW`; the protest becomes `WITHDRAWN` and the line returns to
        `PENDING`, a compensating action restoring the pre-protest ledger
        posture."

        Design: Difficulty/compensating_invariant/protest_withdrawal_restores_line_and_totals
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        ctx = setup_statement_with_line(amount_cents=400_000,
                                        erroneous_reason="WRONG_EMPLOYER")
        protest = file_protest(ctx["line"]["id"], ctx["statement"]["id"],
                               protest_basis="WRONG_EMPLOYER")
        review_protest(protest["id"])
        assert get_protest(protest["id"])["status"] == "UNDER_REVIEW"

        withdrawn = validate_success(api.withdraw_protest(protest["id"], AUDITOR), 200)
        assert withdrawn["status"] == "WITHDRAWN"
        assert get_line_item(ctx["line"]["id"])["status"] == "PENDING"
        assert get_statement(ctx["statement"]["id"])["total_charged_cents"] == 400_000


class TestWaiveCompensation:
    def test_waive_restores_reserve_without_protest_credit(self, api):
        """PRD §3.6: "An `AgencyLiaison` waiving a line in `PENDING` (otherwise
        `ERR_LINE_NOT_WAIVABLE`) moves it to `WAIVED` and applies the same
        three-ledger adjustment as a reversal — statement total down, claim
        charged down, employer reserve up, each by the line's amount — but no
        `protest_credits_cents` accrue, because a waive is agency goodwill
        rather than an employer protest win."

        Design: Difficulty/compensating_invariant/waive_restores_reserve_without_protest_credit
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        ctx = setup_statement_with_line(
            amount_cents=250_000, erroneous_reason=None,
            employer_kwargs={"legal_name": "WaiveCo",
                             "reserve_balance_cents": 10_000_000})
        assert get_employer(ctx["employer"]["id"])["reserve_balance_cents"] == 9_750_000

        waived = validate_success(api.waive_line_item(ctx["line"]["id"], LIAISON), 200)
        assert waived["status"] == "WAIVED"
        assert get_statement(ctx["statement"]["id"])["total_charged_cents"] == 0
        assert get_claim(ctx["claim"]["id"])["charged_amount_cents"] == 0
        employer_after = get_employer(ctx["employer"]["id"])
        assert employer_after["reserve_balance_cents"] == 10_000_000
        assert employer_after["protest_credits_cents"] == 0

    def test_waive_non_pending_line_rejected(self, api):
        """PRD §3.6: "An `AgencyLiaison` waiving a line in `PENDING` (otherwise
        `ERR_LINE_NOT_WAIVABLE`)"

        Design: Difficulty/compensating_invariant/waive_restores_reserve_without_protest_credit
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        ctx = setup_statement_with_line(amount_cents=250_000,
                                        erroneous_reason=None)
        validate_success(api.waive_line_item(ctx["line"]["id"], LIAISON), 200)

        err = api.waive_line_item(ctx["line"]["id"], LIAISON)
        validate_error(err, ApiErrorId.ERR_LINE_NOT_WAIVABLE, 409)
        assert get_line_item(ctx["line"]["id"])["status"] == "WAIVED"


class TestProtestFilingRules:
    def test_already_protested_basis_requires_prior_denial(self, api):
        """PRD §3.6: "a basis of `ALREADY_PROTESTED` is allowed only when a
        prior protest on the same line was `DENIED` (otherwise
        `ERR_LINE_ALREADY_PROTESTED`)"

        Design: Corner/errors/error_line_already_protested
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        ctx = setup_statement_with_line(amount_cents=100_000,
                                        erroneous_reason="ALREADY_PROTESTED")
        # First protest (on another basis) is filed and withdrawn: the line is
        # PENDING again and no protest on it was ever DENIED.
        first = file_protest(ctx["line"]["id"], ctx["statement"]["id"],
                             protest_basis="WRONG_EMPLOYER")
        validate_success(api.withdraw_protest(first["id"], AUDITOR), 200)
        assert get_line_item(ctx["line"]["id"])["status"] == "PENDING"

        version = get_statement(ctx["statement"]["id"])["version"]
        err = api.file_protest(ctx["line"]["id"], "ALREADY_PROTESTED", version,
                               AUDITOR)
        validate_error(err, ApiErrorId.ERR_LINE_ALREADY_PROTESTED, 409)

    def test_occ_stale_statement_version_on_protest(self, api):
        """PRD §2.9: "requires `expected_statement_version` carrying the
        client's last observed `version` of the parent charge statement. A
        sibling protest that reversed a line recomputes the statement's totals
        and advances its version; protest decisions are always made against
        current statement totals."
        PRD §3.6: "The statement's `version` increments by one with each
        posting."

        Design: Corner/cross_cutting_layers/occ_stale_statement_version_on_protest
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        ctx = setup_statement_with_line(amount_cents=100_000,
                                        erroneous_reason="WRONG_EMPLOYER")
        stale_version = get_statement(ctx["statement"]["id"])["version"]
        # A sibling posting advances the statement's version.
        post_line(ctx["statement"]["id"], ctx["claim"]["id"], 50_000,
                  benefit_weeks=1)

        err = api.file_protest(ctx["line"]["id"], "WRONG_EMPLOYER",
                               stale_version, AUDITOR)
        validate_error(err, ApiErrorId.ERR_STALE_VERSION, 412)
        assert get_line_item(ctx["line"]["id"])["status"] == "PENDING"
