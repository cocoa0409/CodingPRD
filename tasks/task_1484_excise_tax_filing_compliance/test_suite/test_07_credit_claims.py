"""Credit and refund claims: lifecycle, eligibility, caps, reversals
(PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    apply_claim,
    approve_claim,
    create_claim,
    create_rated_event,
    file_return,
    make_analyst_headers,
    make_reviewer_headers,
    new_admin_headers,
    new_analyst_headers,
    new_reviewer_headers,
    setup_active_registration,
    setup_applied_export_claim,
    setup_filed_return,
    submit_claim,
    validate_error,
    validate_success,
)


def _filed_export_return(quantity_units=1000, **kwargs):
    """Filed 2026-08 return over one EXPORT event; returns (ctx, ev, filed)."""
    overrides = {"is_export": True, "quantity_units": quantity_units}
    overrides.update(kwargs)
    return setup_filed_return(event_overrides=overrides)


class TestClaimTerminalLockdown:
    def test_terminal_lockdown_withdrawn_claim_rejected(self, api):
        """PRD §3.8: "A claim in `DRAFT` or `SUBMITTED` may instead be
        withdrawn, ending in `WITHDRAWN`." — `WITHDRAWN` is terminal, so a
        later submit fails per §2.10 "(5) state legality of the requested
        transition, including terminal-state lockdown, yielding
        `ERR_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/terminal_lockdown_withdrawn_claim_rejected
        """
        ctx, ev, filed = _filed_export_return()
        clm = create_claim(ctx["registration"], filed, [ev["id"]])
        withdrawn = validate_success(
            api.withdraw_credit_claim(clm["id"], new_analyst_headers()))
        assert withdrawn["status"] == "WITHDRAWN"
        resp = api.submit_credit_claim(clm["id"], new_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestClaimApprovalCeiling:
    def test_claim_cap_and_overclaimed_approval_rejected(self, api):
        """PRD §3.8: "Approving takes an `approved_cents` that may not exceed
        the smallest of the `claimed_cents`, the computed `eligible_cents`,
        and a statutory cap of 5,000,000 cents (fifty thousand dollars); an
        amount above that ceiling is rejected with
        `ERR_CLAIM_EXCEEDS_ELIGIBLE`."

        Design: Corner/calculations/claim_cap_and_overclaimed_approval_rejected
        """
        ctx = setup_active_registration()
        ev1 = create_rated_event(ctx["registration"], ctx["jurisdiction"],
                                 ctx["product_class"], quantity_units=1000000,
                                 is_export=True)  # tax 24300000
        ev2 = create_rated_event(ctx["registration"], ctx["jurisdiction"],
                                 ctx["product_class"],
                                 event_date="2026-08-04T00:00:00Z",
                                 quantity_units=1000, is_export=True)
        ret_id = ev1["return_id"]
        validate_success(api.submit_return(ret_id, new_analyst_headers()))
        filed = file_return(ret_id)

        submitter = new_analyst_headers()
        reviewer = new_reviewer_headers()
        clm_a = create_claim(ctx["registration"], filed, [ev1["id"]],
                             claimed_cents=10000000,
                             justification="big export", headers=submitter)
        submit_claim(clm_a["id"], headers=submitter)
        clm_b = create_claim(ctx["registration"], filed, [ev2["id"]],
                             claimed_cents=20000, justification="small export",
                             headers=submitter)
        submit_claim(clm_b["id"], headers=submitter)

        # min(claimed 10000000, eligible 24300000, cap 5000000) == 5000000.
        resp_over = api.approve_credit_claim(clm_a["id"], 5000001, reviewer)
        validate_error(resp_over, ApiErrorId.ERR_CLAIM_EXCEEDS_ELIGIBLE)

        at_cap = validate_success(
            api.approve_credit_claim(clm_a["id"], 5000000, reviewer))
        assert at_cap["status"] == "APPROVED"
        assert at_cap["approved_cents"] == 5000000

        # min(claimed 20000, eligible 24300, cap ...) == 20000: claimed binds.
        resp_b = api.approve_credit_claim(clm_b["id"], 24300, reviewer)
        validate_error(resp_b, ApiErrorId.ERR_CLAIM_EXCEEDS_ELIGIBLE)


class TestClaimSubmitReferential:
    def test_already_claimed_event_rejected_at_submit(self, api):
        """PRD §3.8: "And no listed event may already appear on another claim
        in `SUBMITTED`, `APPROVED`, or `APPLIED`, failing with
        `ERR_EVENT_ALREADY_CLAIMED`."

        Design: Corner/validations/already_claimed_event_rejected_at_submit
        """
        ctx, ev, filed, _applied = setup_applied_export_claim()
        clm2 = create_claim(ctx["registration"], filed, [ev["id"]],
                            justification="double dip")
        resp = api.submit_credit_claim(clm2["id"], new_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_EVENT_ALREADY_CLAIMED)

    def test_export_claim_without_export_docs_rejected(self, api):
        """PRD §3.8: "An `EXPORT` claim must list only events whose
        `is_export` flag is set, failing with
        `ERR_EXPORT_DOCUMENTATION_MISSING` otherwise."

        Design: Corner/validations/export_claim_without_export_docs_rejected
        """
        ctx, ev, filed = setup_filed_return()  # non-export event
        clm = create_claim(ctx["registration"], filed, [ev["id"]],
                           justification="no docs")
        resp = api.submit_credit_claim(clm["id"], new_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_EXPORT_DOCUMENTATION_MISSING)

    def test_cross_registrant_claim_reference_rejected(self, api):
        """PRD §2.11: "Any referenced entity that belongs to a different
        registrant chain — a bond issued for another registration, events of
        another registration pulled into an amendment through `add_event_ids`,
        and so on — is rejected with `ERR_CROSS_REGISTRANT_REFERENCE` (HTTP
        422)."

        Design: Corner/validations/cross_registrant_claim_reference_rejected
        """
        ctx1, ev1, filed1 = _filed_export_return()
        ctx2 = setup_active_registration(
            jurisdiction_overrides={"code": "NV-TX", "name": "Nevada"})
        resp = api.create_credit_claim(
            {"registration_id": ctx2["registration"]["id"],
             "return_id": filed1["id"], "claim_type": "EXPORT",
             "claimed_cents": 24300, "event_ids": [ev1["id"]],
             "justification": "poach"},
            new_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_CROSS_REGISTRANT_REFERENCE)


class TestClaimWindows:
    def test_claim_window_expired_rejected(self, api):
        """PRD §3.8: "no later than seven hundred thirty-one days after it,
        as are `EXPORT` claims, with later attempts failing with
        `ERR_CLAIM_WINDOW_EXPIRED`."

        Design: Corner/validations/claim_window_expired_rejected
        """
        ctx, ev, filed = _filed_export_return()
        clm = create_claim(ctx["registration"], filed, [ev["id"]],
                           justification="late claim")
        # Filed at the default clock 2026-08-01; +731 days is 2028-08-01.
        validate_success(
            api.set_clock("2028-08-02T00:00:00Z", new_admin_headers()))
        resp = api.submit_credit_claim(clm["id"], new_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_CLAIM_WINDOW_EXPIRED)


class TestClaimReversalBound:
    def test_claim_reverse_above_applied_rejected(self, api):
        """PRD §3.8: "Reversal takes an `amount_cents` no greater than the
        not-yet-reversed portion — `applied_cents` minus `reversed_cents` —
        failing with `ERR_REVERSE_EXCEEDS_APPLIED` above that."

        Design: Corner/validations/claim_reverse_above_applied_rejected
        """
        _ctx, _ev, _filed, applied = setup_applied_export_claim()
        resp = api.reverse_credit_claim(
            applied["id"], 24400, new_reviewer_headers())
        validate_error(resp, ApiErrorId.ERR_REVERSE_EXCEEDS_APPLIED)


class TestClaimSegregationOfDuties:
    def test_sod_claim_self_approve_forbidden(self, api):
        """PRD §3.8: "Review is segregated per §2.9: the approver or denier
        must not be the operator who submitted the claim, with violations
        rejected as `ERR_SEGREGATION_OF_DUTIES`."
        PRD §2.9: "Preparer and approver must be different operators on every
        approval-style workflow, compared by `X-User-ID`."

        Design: Corner/rbac/sod_claim_self_approve_forbidden
        """
        ctx, ev, filed = _filed_export_return()
        submitter = make_analyst_headers("analyst-1")
        clm = create_claim(ctx["registration"], filed, [ev["id"]],
                           headers=submitter)
        submit_claim(clm["id"], headers=submitter)
        # A reviewer ROLE presenting the submitter's X-User-ID is still the
        # same operator and is rejected.
        resp = api.approve_credit_claim(
            clm["id"], 24300, make_reviewer_headers("analyst-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


class TestDeniedResubmitLoop:
    def _setup_denied_claim(self, api):
        ctx, ev, filed = _filed_export_return()
        submitter = make_analyst_headers("analyst-1")
        clm = create_claim(ctx["registration"], filed, [ev["id"]],
                           justification="round 1", headers=submitter)
        submit_claim(clm["id"], headers=submitter)
        denied = validate_success(api.deny_credit_claim(
            clm["id"], "insufficient documentation",
            make_reviewer_headers("reviewer-1")))
        assert denied["status"] == "DENIED"
        return ctx, ev, filed, clm

    def test_denied_claim_resubmit_clears_review_state(self, api):
        """PRD §3.8: "A denied claim is not dead: resubmission sends it from
        `DENIED` back to `DRAFT`, clearing `submitted_by_user_id`,
        `reviewed_by_user_id`, and `eligible_cents` so the cycle can run
        again."

        Design: Difficulty/non_linear_state_machine/credit_claim_denied_resubmit_loop
        """
        _ctx, _ev, _filed, clm = self._setup_denied_claim(api)
        back = validate_success(
            api.resubmit_credit_claim(clm["id"], new_analyst_headers()))
        assert back["status"] == "DRAFT"
        assert back["submitted_by_user_id"] is None
        assert back["reviewed_by_user_id"] is None
        assert back["eligible_cents"] == 0

    def test_resubmitted_claim_recomputes_eligible_and_approves(self, api):
        """PRD §3.8: "On a valid submission the server records
        `submitted_by_user_id` and computes `eligible_cents`: the sum of
        `tax_cents` over the claim's listed events whose status is `RETURNED`
        or `ADJUSTED`" — after the DENIED -> DRAFT loop the second submission
        recomputes eligibility and a different reviewer approves.

        Design: Difficulty/non_linear_state_machine/credit_claim_denied_resubmit_loop
        """
        _ctx, _ev, _filed, clm = self._setup_denied_claim(api)
        validate_success(
            api.resubmit_credit_claim(clm["id"], new_analyst_headers()))
        submitter2 = make_analyst_headers("analyst-9")
        resubmitted = validate_success(
            api.submit_credit_claim(clm["id"], submitter2))
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["eligible_cents"] == 24300
        assert resubmitted["submitted_by_user_id"] == "analyst-9"

        approved = validate_success(api.approve_credit_claim(
            clm["id"], 24300, make_reviewer_headers("reviewer-9")))
        assert approved["status"] == "APPROVED"


class TestClaimApplyReverseConservation:
    def test_claim_apply_then_full_reverse_restores_net_due(self, api):
        """PRD §3.8: "Application sets `applied_cents` equal to
        `approved_cents`, adds that amount to the return's `credits_cents`,
        recomputes `net_due_cents`" and "Each reversal adds to
        `reversed_cents`, subtracts the amount from the return's
        `credits_cents`, recomputes the net due" — a full compensating
        reverse restores the pre-claim ledger exactly (no drift).

        Design: Difficulty/compensating_invariant/claim_apply_reverse_conserves_return_credit_ledger
        """
        # No deposits paid: filing computes net 26730 = 24300 tax + 2430
        # underpayment penalty (PRD §3.6 pinned steps 4-5).
        ctx, ev, filed = _filed_export_return()
        assert filed["net_due_cents"] == 26730

        clm = create_claim(ctx["registration"], filed, [ev["id"]])
        submit_claim(clm["id"], headers=make_analyst_headers("analyst-1"))
        approve_claim(clm["id"], 24300,
                      headers=make_reviewer_headers("reviewer-1"))
        apply_claim(clm["id"])

        mid = validate_success(api.get_return(filed["id"], new_analyst_headers()))
        assert mid["credits_cents"] == 24300
        # PRD step 5: 24300 - 24300 - 0 + 2430 = 2430.
        assert mid["net_due_cents"] == 2430

        validate_success(api.reverse_credit_claim(
            clm["id"], 24300, make_reviewer_headers("reviewer-2")))
        post = validate_success(api.get_return(filed["id"], new_analyst_headers()))
        assert post["credits_cents"] == 0
        assert post["net_due_cents"] == 26730, "invariant restored"

    def test_full_reverse_lands_claim_in_reversed(self, api):
        """PRD §3.8: "A claim whose reversed total has not yet reached its
        applied amount stays `APPLIED`; when the reversed total reaches the
        applied amount, the claim moves to `REVERSED`."

        Design: Difficulty/compensating_invariant/claim_apply_reverse_conserves_return_credit_ledger
        """
        ctx, ev, filed = _filed_export_return()
        clm = create_claim(ctx["registration"], filed, [ev["id"]])
        submit_claim(clm["id"], headers=make_analyst_headers("analyst-1"))
        approve_claim(clm["id"], 24300,
                      headers=make_reviewer_headers("reviewer-1"))
        apply_claim(clm["id"])
        validate_success(api.reverse_credit_claim(
            clm["id"], 24300, make_reviewer_headers("reviewer-2")))
        claim = validate_success(
            api.get_credit_claim(clm["id"], new_analyst_headers()))
        assert claim["status"] == "REVERSED"
        assert claim["reversed_cents"] == 24300
        assert claim["reversed_cents"] == claim["applied_cents"]


class TestClaimApplySettlementCascade:
    def test_claim_apply_flips_settlement_to_overpaid(self, api):
        """PRD §3.6: "When a claim application reduces a return's net due to
        zero or below, its settlement flips from `AWAITING_PAYMENT` to
        `SETTLED` or `OVERPAID`" and "A settlement transition never changes
        the filing status, and a filing transition never changes the
        settlement status directly."

        Design: Difficulty/transitive_cascade/claim_apply_settlement_overpayment_cascade
        """
        ctx, ev, filed, clm = _settled_return_with_approved_claim(api)
        assert filed["settlement_status"] == "SETTLED"

        validate_success(api.apply_credit_claim(clm["id"], new_analyst_headers()))
        ret = validate_success(api.get_return(filed["id"], new_analyst_headers()))
        assert ret["credits_cents"] == 24300
        assert ret["net_due_cents"] == -24300
        assert ret["settlement_status"] == "OVERPAID"
        assert ret["filing_status"] == "FILED", (
            "the settlement axis moved alone; filing_status is untouched")

    def test_claim_apply_overpaid_excess_accrues_to_registrant(self, api):
        """PRD §3.6: "a negative net due adds its absolute amount to the
        registrant's `overpayment_balance_cents`."

        Design: Difficulty/transitive_cascade/claim_apply_settlement_overpayment_cascade
        """
        ctx, _ev, filed, clm = _settled_return_with_approved_claim(api)
        validate_success(api.apply_credit_claim(clm["id"], new_analyst_headers()))
        rgt = validate_success(
            api.get_registrant(ctx["registrant"]["id"], new_analyst_headers()))
        assert rgt["overpayment_balance_cents"] == 24300


def _settled_return_with_approved_claim(api):
    """Filed EXPORT return with depA paid in full (net 0, SETTLED) plus an
    APPROVED claim for the full event tax. Returns (ctx, event, filed, claim)."""
    ctx = setup_active_registration()
    ev = create_rated_event(ctx["registration"], ctx["jurisdiction"],
                            ctx["product_class"], quantity_units=1000,
                            is_export=True)
    ret_id = ev["return_id"]
    from test_helpers import list_period_deposits
    dep_a = list_period_deposits(ctx["registration"]["id"], "2026-08")[0]
    validate_success(api.pay_deposit(dep_a["id"], 24300, new_analyst_headers()))
    validate_success(api.submit_return(ret_id, new_analyst_headers()))
    filed = file_return(ret_id)
    assert filed["settlement_status"] == "SETTLED"

    clm = create_claim(ctx["registration"], filed, [ev["id"]],
                       headers=make_analyst_headers("analyst-1"))
    submit_claim(clm["id"], headers=make_analyst_headers("analyst-1"))
    approve_claim(clm["id"], 24300, headers=make_reviewer_headers("reviewer-1"))
    return ctx, ev, filed, clm
