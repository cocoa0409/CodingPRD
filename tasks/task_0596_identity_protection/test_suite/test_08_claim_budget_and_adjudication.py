"""Adjudication, payment, reversal, and the lifetime insurance budget (PRD §3.7, §2.8)."""

from test_helpers import (
    SIX_LINE_EXPENSES,
    ApiErrorId,
    assert_insurance_budget_conserved,
    create_claim,
    expense,
    get_claim,
    get_subscriber,
    make_adjuster_headers,
    make_admin_headers,
    make_subscriber_headers,
    raise_underwriting_risk,
    setup_approved_claim,
    setup_draft_claim,
    setup_submitted_claim,
    submit_claim,
    validate_error,
    validate_success,
)

SSN_ALERT = {"alert_type": "SSN_TRACE", "severity": "MEDIUM",
             "source_detail": "SSN used to open store card"}
SMALL_PLAN = {
    "tier": "STANDARD",
    "monthly_fee_cents": 999,
    "insurance_limit_cents": 100000,
    "max_family_members": 1,
    "child_monitoring_included": False,
}


def _approved_claim_with_second_draft():
    """A 100000-limit subscriber whose approved claim will exhaust the budget, plus a second
    DRAFT claim already sitting on the same resolved case."""
    ctx = setup_approved_claim(
        expenses=[expense("LEGAL_FEES", 102500, True)],
        plan_overrides=SMALL_PLAN,
        alert_overrides=SSN_ALERT,
        adjuster_user_id="adjuster-003",
    )
    # Claim A is APPROVED (not DRAFT), so opening claim B supersedes nothing.
    ctx["claim_b"] = create_claim(
        ctx["case"]["id"], ctx["subscriber"]["id"], [expense("NOTARY", 9000, True)]
    )
    return ctx


class TestPayCascade:
    """pay -> insurance_remaining_cents -> EXHAUSTED -> the next submit is refused."""

    def test_payment_drains_the_budget_and_flips_the_subscriber_to_exhausted(self, api):
        """PRD §3.7: "Payment then cascades into the budget: the subscriber's
        `insurance_remaining_cents` is recomputed as the plan's `insurance_limit_cents` minus the
        total of `approved_cents` across every one of that subscriber's claims currently in `PAID` —
        claims in `DRAFT`, `SUBMITTED`, `APPROVED`, `DENIED`, `REVERSED` or `SUPERSEDED` contribute
        nothing. If the recomputed remaining reaches zero or below, `insurance_status` becomes
        `EXHAUSTED`; a remaining of exactly zero *is* exhausted."

        Design: Difficulty/transitive_cascade/pay_cascade_remaining_then_exhausted_then_submit_blocked
        """
        ctx = _approved_claim_with_second_draft()
        # 102500 in full, less the 2500 deductible, capped by the 100000 remaining.
        assert ctx["claim"]["approved_cents"] == 100000

        paid = validate_success(
            api.pay_claim(ctx["claim"]["id"], make_admin_headers("admin-009"))
        )
        assert paid["status"] == "PAID"

        subscriber = get_subscriber(ctx["subscriber"]["id"])
        assert subscriber["insurance_remaining_cents"] == 0
        assert subscriber["insurance_status"] == "EXHAUSTED", "a remaining of exactly zero"
        assert_insurance_budget_conserved(subscriber, 100000, [get_claim(ctx["claim"]["id"])])

    def test_an_exhausted_subscriber_can_submit_no_further_claim(self, api):
        """PRD §3.7: "And an exhausted subscriber can submit no further claims: their next
        submission is refused with `ERR_INSURANCE_EXHAUSTED`."
        PRD §3.7: "the subscriber's `insurance_status` must be `AVAILABLE` (else
        `ERR_INSURANCE_EXHAUSTED`)"

        Design: Difficulty/transitive_cascade/pay_cascade_remaining_then_exhausted_then_submit_blocked
        """
        ctx = _approved_claim_with_second_draft()
        validate_success(api.pay_claim(ctx["claim"]["id"], make_admin_headers("admin-009")))
        assert get_subscriber(ctx["subscriber"]["id"])["insurance_status"] == "EXHAUSTED"

        resp = api.submit_claim(
            ctx["claim_b"]["id"], make_subscriber_headers(ctx["subscriber"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INSURANCE_EXHAUSTED)

        claim_b = get_claim(ctx["claim_b"]["id"])
        assert claim_b["status"] == "DRAFT", "the refused submit changed nothing"
        assert claim_b["provisional_amount_cents"] is None


class TestSubmitPrecedence:
    """State legality is screened before the insurance-budget gate."""

    def test_resubmitting_a_submitted_claim_reports_invalid_state_not_exhausted(self, api):
        """PRD §2.5: "When several checks could reject the same request, the order in which they are
        evaluated is normative, because it determines *which* error the caller sees. Requests are
        screened in the following sequence, and the first failing check short-circuits the request:"
        PRD §3.7: "Four conditions must hold, and their order determines the error the subscriber
        sees: the claim must be `DRAFT` (else `ERR_INVALID_STATE`); the referenced case must be
        `RESOLVED` (else `ERR_CASE_NOT_RESOLVED`); the subscriber's enrollment must be `ACTIVE`
        (else `ERR_ENROLLMENT_NOT_ACTIVE`); the subscriber's `insurance_status` must be `AVAILABLE`
        (else `ERR_INSURANCE_EXHAUSTED`); and the subscriber's `underwriting_risk_score` must be at
        most 75 — a score of exactly 75 passes, 76 does not (else
        `ERR_UNDERWRITING_RISK_TOO_HIGH`)."

        Design: Difficulty/priority_pair_validation_conflict/submit_state_beats_fiscal_exhausted
        """
        ctx = setup_approved_claim(
            expenses=[expense("LEGAL_FEES", 102500, True)],
            plan_overrides=SMALL_PLAN,
            alert_overrides=SSN_ALERT,
            adjuster_user_id="adjuster-004",
        )
        subscriber_id = ctx["subscriber"]["id"]
        claim_b = create_claim(
            ctx["case"]["id"], subscriber_id, [expense("POSTAGE", 6000, True)]
        )
        submit_claim(claim_b["id"], subscriber_id)  # accepted while insurance is still AVAILABLE
        validate_success(api.pay_claim(ctx["claim"]["id"], make_admin_headers("admin-010")))

        resp = api.submit_claim(claim_b["id"], make_subscriber_headers(subscriber_id))
        error = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert error["error_id"] != "ERR_INSURANCE_EXHAUSTED", (
            "the fiscal rule must not pre-empt the state rule"
        )

    def test_both_rules_are_genuinely_violated_and_the_claim_stays_submitted(self, api):
        """PRD §2.5: "When several checks could reject the same request, the order in which they are
        evaluated is normative, because it determines *which* error the caller sees. Requests are
        screened in the following sequence, and the first failing check short-circuits the request:"
        PRD §3.7: "And an exhausted subscriber can submit no further claims: their next submission
        is refused with `ERR_INSURANCE_EXHAUSTED`."

        Design: Difficulty/priority_pair_validation_conflict/submit_state_beats_fiscal_exhausted
        """
        ctx = setup_approved_claim(
            expenses=[expense("LEGAL_FEES", 102500, True)],
            plan_overrides=SMALL_PLAN,
            alert_overrides=SSN_ALERT,
            adjuster_user_id="adjuster-004",
        )
        subscriber_id = ctx["subscriber"]["id"]
        claim_b = create_claim(
            ctx["case"]["id"], subscriber_id, [expense("POSTAGE", 6000, True)]
        )
        submit_claim(claim_b["id"], subscriber_id)
        validate_success(api.pay_claim(ctx["claim"]["id"], make_admin_headers("admin-010")))

        subscriber = get_subscriber(subscriber_id)
        assert subscriber["insurance_status"] == "EXHAUSTED", "the fiscal rule is violated too"
        assert get_claim(claim_b["id"])["status"] == "SUBMITTED", "the state rule is violated"

        validate_error(
            api.submit_claim(claim_b["id"], make_subscriber_headers(subscriber_id)),
            ApiErrorId.ERR_INVALID_STATE,
        )
        assert get_claim(claim_b["id"])["status"] == "SUBMITTED", (
            "the rejected call left the claim exactly where it was"
        )


class TestBudgetConservation:
    """Pay-then-reverse must leave the budget bit-for-bit where it started."""

    def test_payment_moves_the_budget_by_exactly_the_approved_amount(self, api):
        """PRD §2.8: "Second, **reimbursement-budget conservation**: for every subscriber, the
        plan's `insurance_limit_cents` always equals `insurance_remaining_cents` plus the total of
        `approved_cents` over that subscriber's paid claims."
        PRD §3.7: "Payment then cascades into the budget: the subscriber's
        `insurance_remaining_cents` is recomputed as the plan's `insurance_limit_cents` minus the
        total of `approved_cents` across every one of that subscriber's claims currently in `PAID` —
        claims in `DRAFT`, `SUBMITTED`, `APPROVED`, `DENIED`, `REVERSED` or `SUPERSEDED` contribute
        nothing."

        Design: Difficulty/compensating_invariant/pay_then_reverse_conserves_insurance_budget
        """
        ctx = setup_approved_claim(
            expenses=SIX_LINE_EXPENSES,
            alert_overrides={"alert_type": "SSN_TRACE", "severity": "MEDIUM",
                             "source_detail": "SSN used for unemployment claim"},
            adjuster_user_id="adjuster-005",
        )
        assert ctx["claim"]["approved_cents"] == 374503
        before = get_subscriber(ctx["subscriber"]["id"])
        assert before["insurance_remaining_cents"] == 500000, (
            "approval alone does not move the ledger"
        )

        validate_success(api.pay_claim(ctx["claim"]["id"], make_admin_headers("admin-011")))

        paid_claim = get_claim(ctx["claim"]["id"])
        assert paid_claim["status"] == "PAID"
        after = get_subscriber(ctx["subscriber"]["id"])
        assert after["insurance_remaining_cents"] == 125497
        assert_insurance_budget_conserved(after, 500000, [paid_claim])

    def test_reversal_restores_the_budget_with_zero_drift(self, api):
        """PRD §3.7: "An administrator claws back a `PAID` claim by supplying a `reversal_reason`,
        carrying it `PAID → REVERSED` — terminal. The claim leaves the paid set, so
        `insurance_remaining_cents` recomputes by the same rule and returns to precisely its
        pre-payment value, and `insurance_status` returns to `AVAILABLE` whenever the recomputed
        remaining is above zero. Pay-then-reverse must leave the budget bit-for-bit where it
        started."
        PRD §2.8: "Paying a claim and then reversing it must restore `insurance_remaining_cents` and
        `insurance_status` to their exact pre-payment values, with no drift."

        Design: Difficulty/compensating_invariant/pay_then_reverse_conserves_insurance_budget
        """
        ctx = setup_approved_claim(
            expenses=SIX_LINE_EXPENSES,
            alert_overrides={"alert_type": "SSN_TRACE", "severity": "MEDIUM",
                             "source_detail": "SSN used for unemployment claim"},
            adjuster_user_id="adjuster-005",
        )
        validate_success(api.pay_claim(ctx["claim"]["id"], make_admin_headers("admin-011")))
        assert get_subscriber(ctx["subscriber"]["id"])["insurance_remaining_cents"] == 125497

        reversed_claim = validate_success(
            api.reverse_claim(
                ctx["claim"]["id"],
                {"reversal_reason": "Duplicate disbursement detected by treasury"},
                make_admin_headers("admin-011"),
            )
        )
        assert reversed_claim["status"] == "REVERSED"
        assert reversed_claim["approved_cents"] == 374503, "the approved figure is not erased"

        after = get_subscriber(ctx["subscriber"]["id"])
        assert after["insurance_remaining_cents"] == 500000, "back to the pre-payment value"
        assert after["insurance_status"] == "AVAILABLE"
        assert_insurance_budget_conserved(after, 500000, [reversed_claim])


class TestTerminalStatesAndGates:
    def test_paying_a_denied_claim_is_rejected(self, api):
        """PRD §3.7: "Denial carries it `SUBMITTED → DENIED` — a terminal state — records the
        supplied `denial_reason`, and leaves `approved_cents` null."
        PRD §3.7: "An `APPROVED` claim is disbursed, carrying it `APPROVED → PAID`, but only if the
        paying administrator's `X-User-ID` differs from the `approved_by_user_id` stored on the
        claim."

        Design: Corner/state_machines/claim_pay_after_deny_rejected_terminal_lockdown
        """
        ctx = setup_submitted_claim(
            expenses=[expense("LEGAL_FEES", 50000, True)],
            alert_overrides={"alert_type": "SSN_TRACE", "severity": "MEDIUM",
                             "source_detail": "SSN on phone contract"},
        )
        denied = validate_success(
            api.deny_claim(
                ctx["claim"]["id"],
                {"denial_reason": "Expenses not covered by policy"},
                make_adjuster_headers("adjuster-100"),
            )
        )
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "Expenses not covered by policy"
        assert denied["approved_cents"] is None
        assert denied["provisional_amount_cents"] == 47500, "50000 less the 2500 deductible"

        resp = api.pay_claim(ctx["claim"]["id"], make_admin_headers("admin-100"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        subscriber = get_subscriber(ctx["subscriber"]["id"])
        assert subscriber["insurance_remaining_cents"] == 500000, "a DENIED claim pays nothing"
        assert subscriber["insurance_status"] == "AVAILABLE"

    def test_submit_is_refused_when_the_underwriting_number_exceeds_seventy_five(self, api):
        """PRD §3.7: "the subscriber's `underwriting_risk_score` must be at most 75 — a score of
        exactly 75 passes, 76 does not (else `ERR_UNDERWRITING_RISK_TOO_HIGH`)"
        PRD §3.5: "It counts *only* alerts the subscriber has actually confirmed as fraud —
        `CONFIRMED_FRAUD` or `ESCALATED` — and it applies that rule uniformly to all four alert
        types, so a `NEW` credit inquiry and an `ACKNOWLEDGED` dark-web hit are simply invisible to
        it. It never applies the family-child multiplier."

        Design: Corner/validations/claim_submit_with_underwriting_risk_above_75_rejected
        """
        ctx = setup_draft_claim(
            expenses=[expense("LEGAL_FEES", 60000, True)],
            specialist_overrides={"full_name": "Solo Worker", "tier": "TIER3", "max_caseload": 5},
            alert_overrides={"alert_type": "DARK_WEB", "severity": "LOW",
                             "source_detail": "base case alert"},
        )
        subscriber_id = ctx["subscriber"]["id"]
        raise_underwriting_risk(
            subscriber_id,
            [
                ("SSN_TRACE", "MEDIUM", "ssn hit 1"),
                ("SSN_TRACE", "MEDIUM", "ssn hit 2"),
                ("ACCOUNT_TAKEOVER", "MEDIUM", "ato hit"),
                ("CREDIT_INQUIRY", "LOW", "inquiry hit"),
            ],
        )

        subscriber = get_subscriber(subscriber_id)
        # 10 base + 25 + 25 + 20 + 8; the original DARK_WEB alert is RESOLVED and counts for nothing.
        assert subscriber["underwriting_risk_score"] == 88
        assert subscriber["insurance_status"] == "AVAILABLE", "the fiscal rule is not the one firing"

        resp = api.submit_claim(ctx["claim"]["id"], make_subscriber_headers(subscriber_id))
        validate_error(resp, ApiErrorId.ERR_UNDERWRITING_RISK_TOO_HIGH)

        claim = get_claim(ctx["claim"]["id"])
        assert claim["status"] == "DRAFT"
        assert claim["provisional_amount_cents"] is None