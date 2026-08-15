"""Gift payments: waterfall allocation, depth-3 activation cascade, reversal
conservation, outstanding boundary, and the state-vs-fiscal priority pair."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    setup_active_pledge, create_payment, create_campaign,
    get_pledge, get_fund, get_prospect, list_installments,
    create_prospect, create_gift_payment_payload,
)

DIR = TEST_USERS["director_headers"]
FIN = TEST_USERS["finance_headers"]


class TestPaymentCascade:
    """Queue A: transitive_cascade / payment_installment_pledge_fund_activation_cascade."""

    def _setup_endowed_pledge(self):
        return setup_active_pledge(
            3000000, installment_count=3, frequency="MONTHLY",
            first_due_date="2026-08-15T00:00:00Z",
            restriction_type="ENDOWED", purpose_code="SCHOLAR_ENDOW",
        )

    def test_payment_fulfills_pledge_and_activates_fund(self, api):
        """PRD §3.7: "An installment whose `paid_cents` reaches its `amount_cents`
        with no write-off becomes `PAID`, which recomputes the pledge's
        `outstanding_cents` and may fulfill the pledge per §3.6. The credited
        fund — the pledge's fund for a pledge-linked payment, otherwise the
        payload's `fund_id` when present — has its `balance_cents` increased by
        the payment amount, and a fund at or above its `minimum_activation_cents`
        after the credit moves from `PENDING_MINIMUM` to `ACTIVE` with a `version`
        bump."
        PRD §3.6: "it becomes `FULFILLED` when every installment is `PAID` with
        the pledge's `written_off_cents` at zero."

        Design: Difficulty/transitive_cascade/payment_installment_pledge_fund_activation_cascade
        """
        ctx = self._setup_endowed_pledge()
        pl_id, fund_id, p_id = ctx["pledge"]["id"], ctx["fund"]["id"], ctx["p"]["id"]

        create_payment(p_id, 1000000, received_at="2026-08-16T00:00:00Z", pledge_id=pl_id)
        create_payment(p_id, 1000000, received_at="2026-09-16T00:00:00Z", pledge_id=pl_id)
        create_payment(p_id, 1000000, received_at="2026-10-16T00:00:00Z", pledge_id=pl_id)

        rows = list_installments(pl_id)
        assert rows[2]["status"] == "PAID"

        pledge = get_pledge(pl_id)
        assert pledge["status"] == "FULFILLED"
        assert pledge["outstanding_cents"] == 0

        fund = get_fund(fund_id)
        assert fund["balance_cents"] == 3000000
        assert fund["status"] == "ACTIVE"  # 3000000 >= 2500000 minimum

    def test_partial_payments_leave_pledge_active(self, api):
        """PRD §3.6: "it becomes `FULFILLED` when every installment is `PAID`
        with the pledge's `written_off_cents` at zero."
        PRD §3.7: "A pledge-linked payment applies its amount as a **waterfall,
        earliest obligation first**: installments with an open balance are
        visited in ascending `due_date`, ties broken by ascending
        `sequence_number`, and each receives the smaller of the payment's
        remaining amount and its open balance."

        Design: Difficulty/transitive_cascade/payment_installment_pledge_fund_activation_cascade
        """
        ctx = self._setup_endowed_pledge()
        pl_id, fund_id, p_id = ctx["pledge"]["id"], ctx["fund"]["id"], ctx["p"]["id"]

        create_payment(p_id, 1000000, received_at="2026-08-16T00:00:00Z", pledge_id=pl_id)
        create_payment(p_id, 1000000, received_at="2026-09-16T00:00:00Z", pledge_id=pl_id)

        rows = list_installments(pl_id)
        assert rows[0]["status"] == "PAID"
        assert rows[1]["status"] == "PAID"
        assert rows[2]["status"] == "SCHEDULED"

        pledge = get_pledge(pl_id)
        assert pledge["status"] == "ACTIVE"  # not yet fulfilled
        assert pledge["outstanding_cents"] == 1000000

        fund = get_fund(fund_id)
        assert fund["balance_cents"] == 2000000
        assert fund["status"] == "PENDING_MINIMUM"  # 2000000 < 2500000


class TestPaymentReversalConservation:
    """Queue A: compensating_invariant / payment_reversal_restores_conserved_balances."""

    def _setup_campaign_pledge(self):
        campaign = create_campaign()
        ctx = setup_active_pledge(
            3000000, installment_count=3, frequency="MONTHLY",
            first_due_date="2026-08-15T00:00:00Z",
            restriction_type="ENDOWED", purpose_code="GEN_ENDOW",
            campaign_id=campaign["id"],
        )
        ctx["campaign"] = campaign
        return ctx

    def test_reversal_restores_all_conserved_balances(self, api):
        """PRD §3.7: "Reversal sets `reversed` true, stamps `reversed_at` from
        the logical clock, and reconciles every derived field the payment
        touched: each allocation in `applied_allocations` is withdrawn from its
        installment's `paid_cents`; a `PAID` installment reopens to `OVERDUE`
        when the current logical time is already strictly later than its
        `due_date` plus 30 days, otherwise to `REMINDED` when its
        `reminder_count` is above zero, otherwise to `SCHEDULED`; a `FULFILLED`
        pledge returns to `ACTIVE` with its outstanding balance recomputed; the
        credited fund's `balance_cents` is decremented, dropping an `ACTIVE` fund
        back to `PENDING_MINIMUM` when the balance falls below
        `minimum_activation_cents`; campaign totals decrement under both
        variants; and the donor prospect's aggregates and recognition recompute
        with the prospect's `version` advancing."

        Design: Difficulty/compensating_invariant/payment_reversal_restores_conserved_balances
        """
        ctx = self._setup_campaign_pledge()
        pl_id, fund_id, p_id, c_id = (
            ctx["pledge"]["id"], ctx["fund"]["id"], ctx["p"]["id"], ctx["campaign"]["id"],
        )

        pay = create_payment(p_id, 1000000, received_at="2026-08-16T00:00:00Z",
                             pledge_id=pl_id, campaign_id=c_id)

        # Mid-flight effects: outstanding drops, cash counts the payment.
        assert get_pledge(pl_id)["outstanding_cents"] == 2000000
        totals_mid = validate_success(api.get_campaign_totals(c_id, FIN))
        assert totals_mid["cash_counted_cents"] == 1000000
        assert totals_mid["face_value_counted_cents"] == 3000000

        validate_success(api.reverse_gift_payment(pay["id"], FIN))

        pledge = get_pledge(pl_id)
        assert pledge["outstanding_cents"] == 3000000
        assert pledge["status"] == "ACTIVE"

        rows = list_installments(pl_id)
        assert rows[0]["status"] == "SCHEDULED"  # clock 2026-08-01 <= due 08-15 + 30d, no reminders
        assert rows[0]["paid_cents"] == 0

        totals_end = validate_success(api.get_campaign_totals(c_id, FIN))
        assert totals_end["cash_counted_cents"] == 0
        assert totals_end["face_value_counted_cents"] == 3000000  # booking variant unaffected

        assert get_fund(fund_id)["balance_cents"] == 0
        assert get_prospect(p_id)["lifetime_given_cents"] == 0

        payment = validate_success(api.get_gift_payment(pay["id"], FIN))
        assert payment["reversed"] is True

    def test_reversal_marks_payment_and_blocks_second_reversal_effects(self, api):
        """PRD §3.7: "A reversed payment counts toward nothing anywhere in the
        system."
        PRD §3.7: "Reversal sets `reversed` true, stamps `reversed_at` from the
        logical clock, and reconciles every derived field the payment touched."

        Design: Difficulty/compensating_invariant/payment_reversal_restores_conserved_balances
        """
        ctx = self._setup_campaign_pledge()
        pl_id, p_id, c_id = ctx["pledge"]["id"], ctx["p"]["id"], ctx["campaign"]["id"]

        pay = create_payment(p_id, 1000000, received_at="2026-08-16T00:00:00Z",
                             pledge_id=pl_id, campaign_id=c_id)
        reversed_pay = validate_success(api.reverse_gift_payment(pay["id"], FIN))
        assert reversed_pay["reversed"] is True
        assert reversed_pay["reversed_at"] is not None

        # Aggregates fully restored.
        assert get_pledge(pl_id)["outstanding_cents"] == 3000000
        totals = validate_success(api.get_campaign_totals(c_id, FIN))
        assert totals["cash_counted_cents"] == 0
        assert get_prospect(p_id)["lifetime_given_cents"] == 0


class TestPaymentBoundariesAndGuards:
    def test_payment_exact_outstanding_boundary(self, api):
        """PRD §3.7: "a linked pledge must be `ACTIVE` (`ERR_PLEDGE_NOT_ACTIVE`)
        and the payment's `amount_cents` must not exceed the pledge's
        `outstanding_cents` (`ERR_PAYMENT_EXCEEDS_OUTSTANDING`)."

        Design: Corner/validations/payment_exact_outstanding_boundary
        """
        ctx = setup_active_pledge(1000000, installment_count=1, frequency="ANNUAL",
                                  first_due_date="2026-12-01T00:00:00Z")
        pl_id, p_id = ctx["pledge"]["id"], ctx["p"]["id"]

        resp = api.create_gift_payment(
            create_gift_payment_payload(p_id, amount_cents=1000001, pledge_id=pl_id), FIN,
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_OUTSTANDING)

        pay = create_payment(p_id, 1000000, pledge_id=pl_id)
        assert pay["id"]
        pledge = get_pledge(pl_id)
        assert pledge["status"] == "FULFILLED"
        assert pledge["outstanding_cents"] == 0

    def test_payment_reverse_twice_rejected(self, api):
        """PRD §3.7: "Reversal is the books-and-records undo, available to the
        `FinanceSteward` on any payment not already reversed (a second reversal
        fails with `ERR_PAYMENT_ALREADY_REVERSED`)."

        Design: Corner/state_machines/payment_reverse_twice_rejected
        """
        p = create_prospect()
        pay = create_payment(p["id"], 500, payment_method="CHECK")
        validate_success(api.reverse_gift_payment(pay["id"], FIN))

        resp = api.reverse_gift_payment(pay["id"], FIN)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_ALREADY_REVERSED)

        payment = validate_success(api.get_gift_payment(pay["id"], FIN))
        assert payment["reversed"] is True
        assert get_prospect(p["id"])["lifetime_given_cents"] == 0

    def test_payment_non_positive_amount_rejected(self, api):
        """PRD §2.6: "Input money fields must be positive integers unless a rule
        explicitly permits zero."
        PRD §2.10: "The body is well-formed: required fields present, types
        correct, enum values within their declared sets, integer money fields
        positive, unknown fields rejected, and split structures well-formed;
        otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/errors/payment_non_positive_amount_rejected
        """
        p = create_prospect()
        resp = api.create_gift_payment(
            create_gift_payment_payload(p["id"], amount_cents=0, payment_method="CHECK"), FIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestPledgeStateBeatsFiscal:
    """Queue A: priority_pair_validation_conflict / pledge_state_error_beats_fiscal_error."""

    def _written_off_pledge(self, api):
        """A 100-cent pledge fully written off: pledge WRITTEN_OFF, outstanding 0."""
        ctx = setup_active_pledge(100, installment_count=1, frequency="MONTHLY",
                                  first_due_date="2026-09-01T00:00:00Z",
                                  assessed_capacity_cents=1000000,
                                  )
        pl_id = ctx["pledge"]["id"]
        resp = api.create_write_off(pl_id, {"amount_cents": 100, "reason": "UNCOLLECTIBLE"}, FIN)
        wo = validate_success(resp, expected_status=201)
        validate_success(api.review_write_off(wo["id"], {"decision": "APPROVE"}, DIR))
        pledge = get_pledge(pl_id)
        assert pledge["status"] == "WRITTEN_OFF"
        assert pledge["outstanding_cents"] == 0
        return ctx

    def test_payment_against_written_off_pledge_surfaces_state_error(self, api):
        """PRD §2.10: "Every request is validated against an ordered chain of
        checks, and **the first failing check wins**: once an earlier check
        fires, later checks are not evaluated, so the returned error is always
        the highest-priority failure present."
        PRD §2.10: "8. **Entity state preconditions.** ... otherwise the
        state-specific 409 listed with the rule in §3."
        PRD §2.10: "13. **Fiscal limits.** Amounts against outstanding balances,
        split percentages summing to one hundred, and disbursements within the
        spending allowance."
        PRD §3.7: "a linked pledge must be `ACTIVE` (`ERR_PLEDGE_NOT_ACTIVE`) and
        the payment's `amount_cents` must not exceed the pledge's
        `outstanding_cents` (`ERR_PAYMENT_EXCEEDS_OUTSTANDING`)."

        Design: Difficulty/priority_pair_validation_conflict/pledge_state_error_beats_fiscal_error
        """
        ctx = self._written_off_pledge(api)
        # 1-cent payment violates both state (not ACTIVE) and fiscal (1 > 0).
        resp = api.create_gift_payment(
            create_gift_payment_payload(
                ctx["p"]["id"], amount_cents=1, received_at="2026-09-15T00:00:00Z",
                payment_method="CHECK", pledge_id=ctx["pledge"]["id"],
            ),
            FIN,
        )
        validate_error(resp, ApiErrorId.ERR_PLEDGE_NOT_ACTIVE)

    def test_write_off_against_written_off_pledge_also_state_error(self, api):
        """PRD §2.10: "Every request is validated against an ordered chain of
        checks, and **the first failing check wins**: once an earlier check
        fires, later checks are not evaluated, so the returned error is always
        the highest-priority failure present."
        PRD §3.6: "A `GiftOfficer` (owning the prospect) or a `FinanceSteward`
        requests a write-off on an `ACTIVE` pledge (otherwise
        `ERR_PLEDGE_NOT_ACTIVE`) with a positive `amount_cents` and a `reason` of
        `UNCOLLECTIBLE`, `DONOR_HARDSHIP`, `DUPLICATE`, or `OTHER`; the amount
        must not exceed the pledge's `outstanding_cents` at request time
        (`ERR_WRITE_OFF_EXCEEDS_OUTSTANDING`)."

        Design: Difficulty/priority_pair_validation_conflict/pledge_state_error_beats_fiscal_error
        """
        ctx = self._written_off_pledge(api)
        resp = api.create_write_off(
            ctx["pledge"]["id"], {"amount_cents": 1, "reason": "OTHER"}, FIN,
        )
        validate_error(resp, ApiErrorId.ERR_PLEDGE_NOT_ACTIVE)
