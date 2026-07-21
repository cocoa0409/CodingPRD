"""Medicare claim lifecycle: the DENIED<->SUBMITTED cycle, certification/limit
preconditions and their precedence, annual limits, and the paid-then-void compensation."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

BS = TEST_USERS["billing_specialist_headers"]
NON_EXISTENT = "00000000-0000-4000-8000-0000000000aa"


class TestDeniedResubmitCycle:
    """MedicareClaim is cyclic: DENIED can return to SUBMITTED and be DENIED again."""

    def test_resubmit_returns_denied_claim_to_submitted(self, api):
        """PRD §3.6: "A `DENIED` claim may be resubmitted, cycling `DENIED` back to
        `SUBMITTED`."

        Design: Difficulty/non_linear_state_machine/claim_denied_resubmit_cycle
        """
        ctx = fx.setup_fulfilled_medicare_sale(price=30000, allowable=30000, hcpcs="A5500")
        claim = fx.create_draft_claim(ctx, hcpcs="A5500", billed=30000)
        fx.submit_claim(claim["id"])
        fx.adjudicate_claim(claim["id"], "DENIED")
        resubmitted = validate_success(api.resubmit_claim(claim["id"], BS))
        assert resubmitted["status"] == "SUBMITTED"

    def test_resubmitted_claim_can_be_denied_again(self, api):
        """PRD §3.6: "the `DENIED` → `SUBMITTED` → `DENIED` cycle may repeat."

        Design: Difficulty/non_linear_state_machine/claim_denied_resubmit_cycle
        """
        ctx = fx.setup_fulfilled_medicare_sale(price=30000, allowable=30000, hcpcs="A5500")
        claim = fx.create_draft_claim(ctx, hcpcs="A5500", billed=30000)
        fx.submit_claim(claim["id"])
        fx.adjudicate_claim(claim["id"], "DENIED")
        fx.resubmit_claim(claim["id"])
        redenied = validate_success(api.adjudicate_claim(claim["id"], {"payer_decision": "DENIED"}, BS))
        assert redenied["status"] == "DENIED"


class TestSubmitRequiresCompleteCertification:
    """Submitting a claim that cites a SUPERSEDED certification is blocked (no prior PAID
    claim, so only the certification-state dependency can fail)."""

    def test_submit_blocked_when_cited_certification_superseded(self, api):
        """PRD §3.6: "Submitting the claim advances `DRAFT` to `SUBMITTED`. It requires
        that the referenced sale's `fulfillment_status` be `FULFILLED` or
        `PARTIALLY_RETURNED` (else `ERR_SALE_NOT_FULFILLED`) and that the referenced
        certification be `COMPLETE` (else `ERR_CERTIFICATION_INCOMPLETE`)."

        Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_certification_complete
        """
        ctx = fx.setup_customer_with_superseded_cert()
        sale = fx.add_fulfilled_sale(ctx)
        claim = get_success_data(api.create_claim(
            {"customer_id": ctx["customer"]["id"], "sale_id": sale["id"],
             "certification_id": ctx["cert1"]["id"], "hcpcs_code": "A5500",
             "billed_amount_cents": 30000}, BS))
        resp = api.submit_claim(claim["id"], BS)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_INCOMPLETE.value)

    def test_prior_certification_is_superseded_by_newer_one(self, api):
        """PRD §3.6: "A certification begins `COMPLETE`; creating a newer certification
        for the same customer supersedes the prior one, moving it from `COMPLETE` to
        `SUPERSEDED`, and (as noted in §2.7) bumps the customer's `version`."

        Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_certification_complete
        """
        ctx = fx.setup_customer_with_superseded_cert()
        cert1 = fx.get_certification(ctx["customer"]["id"], ctx["cert1"]["id"])
        assert cert1["status"] == "SUPERSEDED"


class TestCertIncompletePrecedesAnnualPairLimit:
    """When a submit violates BOTH the certification-complete check (priority 7) and the
    annual pair limit (priority 18), the higher-priority certification error surfaces."""

    def test_both_violations_report_certification_incomplete(self, api):
        """PRD §2.9: "they are evaluated in a fixed global order, and the first failing
        check determines the response. The order is: (1) authentication ... then the
        domain-specific checks in ascending priority: certification-incomplete
        (`ERR_CERTIFICATION_INCOMPLETE`), sale-not-fulfilled (`ERR_SALE_NOT_FULFILLED`),
        line-already-returned (`ERR_LINE_ALREADY_RETURNED`), exchange-type-mismatch
        (`ERR_EXCHANGE_TYPE_MISMATCH`), quarantined-item (`ERR_ITEM_QUARANTINED`),
        pediatric-size (`ERR_PEDIATRIC_SIZE_TOO_SMALL`), missing-measurement
        (`ERR_MISSING_MEASUREMENT`), fitter-double-booked (`ERR_FITTER_DOUBLE_BOOKED`),
        certification-visit-expired (`ERR_CERTIFICATION_VISIT_EXPIRED`), out-of-stock
        (`ERR_OUT_OF_STOCK`), gait-lab-capacity (`ERR_GAIT_LAB_AT_CAPACITY`),
        annual-pair-limit (`ERR_ANNUAL_PAIR_LIMIT_EXCEEDED`), annual-insert-limit
        (`ERR_ANNUAL_INSERT_LIMIT_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/claim_cert_incomplete_beats_annual_pair_limit
        """
        ctx = fx.setup_paid_then_superseded_second_claim()
        resp = api.submit_claim(ctx["claim2"]["id"], BS)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_INCOMPLETE.value)

    def test_annual_pair_limit_fires_when_certification_complete(self, api):
        """PRD §3.6: "an `A5500` shoe claim requires `medicare_pairs_claimed_ytd` below 1
        (else `ERR_ANNUAL_PAIR_LIMIT_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/claim_cert_incomplete_beats_annual_pair_limit
        """
        ctx, _claim1 = fx.setup_paid_claim(price=30000, allowable=30000, billed=30000)
        sale2 = fx.add_fulfilled_sale(ctx)
        claim2 = fx.create_draft_claim(ctx, hcpcs="A5500", billed=30000, sale_id=sale2["id"])
        resp = api.submit_claim(claim2["id"], BS)
        validate_error(resp, ApiErrorId.ERR_ANNUAL_PAIR_LIMIT_EXCEEDED.value)


class TestAnnualPairLimitBoundary:
    """With exactly one PAID A5500 in the year (pairs_ytd=1), the >=1 limit rejects the
    second A5500 submit."""

    def test_second_a5500_submit_rejected(self, api):
        """PRD §3.6: "an `A5500` shoe claim requires `medicare_pairs_claimed_ytd` below 1
        (else `ERR_ANNUAL_PAIR_LIMIT_EXCEEDED`)."

        Design: Difficulty/boundary_precision_check/annual_pair_limit_second_claim_boundary
        """
        ctx, _claim1 = fx.setup_paid_claim(price=30000, allowable=30000, billed=30000)
        sale2 = fx.add_fulfilled_sale(ctx)
        claim2 = fx.create_draft_claim(ctx, hcpcs="A5500", billed=30000, sale_id=sale2["id"])
        resp = api.submit_claim(claim2["id"], BS)
        validate_error(resp, ApiErrorId.ERR_ANNUAL_PAIR_LIMIT_EXCEEDED.value)

    def test_pairs_claimed_ytd_is_one_after_first_paid(self, api):
        """PRD §3.6: "`medicare_pairs_claimed_ytd` is the number of the customer's `PAID`
        claims whose `hcpcs_code` is `A5500` and whose `calendar_year` equals the current
        clock year."

        Design: Difficulty/boundary_precision_check/annual_pair_limit_second_claim_boundary
        """
        ctx, _claim1 = fx.setup_paid_claim(price=30000, allowable=30000, billed=30000)
        customer = get_success_data(api.get_customer(ctx["customer"]["id"], BS))
        assert customer["medicare_pairs_claimed_ytd"] == 1


class TestVoidRestoresAnnualAllowance:
    """A PAID claim, once VOIDED, restores the customer's regulatory counters."""

    def test_void_restores_pairs_claimed_ytd(self, api):
        """PRD §3.6: "a `PAID` claim may be voided, advancing `PAID` to `VOIDED`; because
        the claim is no longer `PAID`, the customer's `medicare_pairs_claimed_ytd`,
        `medicare_inserts_claimed_ytd`, and `medicare_deductible_remaining_cents` restore
        to their pre-payment values."

        Design: Difficulty/compensating_invariant/medicare_annual_allowance_conserved_paid_then_void
        """
        ctx, claim = fx.setup_paid_claim(price=32000, allowable=30000, billed=32000)
        voided = validate_success(api.void_claim(claim["id"], BS))
        assert voided["status"] == "VOIDED"
        customer = get_success_data(api.get_customer(ctx["customer"]["id"], BS))
        assert customer["medicare_pairs_claimed_ytd"] == 0

    def test_void_restores_deductible_remaining(self, api):
        """PRD §3.6: "a `PAID` claim may be voided, advancing `PAID` to `VOIDED`; because
        the claim is no longer `PAID`, the customer's `medicare_pairs_claimed_ytd`,
        `medicare_inserts_claimed_ytd`, and `medicare_deductible_remaining_cents` restore
        to their pre-payment values."

        Design: Difficulty/compensating_invariant/medicare_annual_allowance_conserved_paid_then_void
        """
        ctx, claim = fx.setup_paid_claim(price=32000, allowable=30000, billed=32000)
        validate_success(api.void_claim(claim["id"], BS))
        customer = get_success_data(api.get_customer(ctx["customer"]["id"], BS))
        assert customer["medicare_deductible_remaining_cents"] == 25700


def test_annual_insert_limit_fourth_claim_rejected(api):
    """PRD §3.6: "an `A5512` or `A5513` insert claim requires `medicare_inserts_claimed_ytd`
    below 3 (else `ERR_ANNUAL_INSERT_LIMIT_EXCEEDED`)."

    Design: Corner/calculations/annual_insert_limit_third_ok_fourth_blocked
    """
    # Three PAID A5512 claims (inserts_ytd=3), then a fourth DRAFT A5512 submit.
    ctx = fx.setup_fulfilled_medicare_sale(price=4000, allowable=4000, hcpcs="A5512",
                                           dob="1942-02-02", mbi="9QR2BO3US51")
    # first insert claim already fulfilled by ctx.sale -> pay it
    claim1 = fx.create_draft_claim(ctx, hcpcs="A5512", billed=4000)
    fx.submit_claim(claim1["id"])
    fx.adjudicate_claim(claim1["id"], "PAID")
    # two more PAID insert claims
    for _ in range(2):
        sale = fx.add_fulfilled_sale(ctx)
        c = fx.create_draft_claim(ctx, hcpcs="A5512", billed=4000, sale_id=sale["id"])
        fx.submit_claim(c["id"])
        fx.adjudicate_claim(c["id"], "PAID")
    customer = get_success_data(api.get_customer(ctx["customer"]["id"], BS))
    assert customer["medicare_inserts_claimed_ytd"] == 3
    # fourth
    sale4 = fx.add_fulfilled_sale(ctx)
    claim4 = fx.create_draft_claim(ctx, hcpcs="A5512", billed=4000, sale_id=sale4["id"])
    resp = api.submit_claim(claim4["id"], BS)
    validate_error(resp, ApiErrorId.ERR_ANNUAL_INSERT_LIMIT_EXCEEDED.value)


def test_submit_nonexistent_claim_returns_not_found(api):
    """PRD §2.8: "Every foreign-key reference — whether supplied as a path identifier or
    inside a request body — must resolve to an existing resource." — the claim not-found
    error is `ERR_CLAIM_NOT_FOUND`.

    Design: Corner/errors/claim_not_found_on_submit
    """
    resp = api.submit_claim(NON_EXISTENT, BS)
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FOUND.value)
