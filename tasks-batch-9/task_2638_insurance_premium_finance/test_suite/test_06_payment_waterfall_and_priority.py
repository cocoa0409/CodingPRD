"""Payment posting: the lifecycle gate that outranks the fiscal ceiling, and the
total-receivable identity across a reversal and a waiver.
"""

from test_helpers import (
    ApiErrorId,
    assert_total_receivable,
    factories,
    fixtures,
    late_fee_cents,
    rule_of_78_rebate_cents,
    total_receivable_cents,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import ANALYST_ORIGIN, COMPLIANCE_WAIVER


def _draft_note(api):
    """A DRAFT note with one 600000 policy: no schedule and no balances yet."""
    ctx = fixtures.origination_context(api)
    bundle = fixtures.draft_agreement(
        api,
        ctx,
        policies=[
            factories.financed_policy(ctx["insurer_id"], policy_number="MC-P-6001")
        ],
    )
    assert bundle["agreement"]["status"] == "DRAFT"
    return bundle


def _activate(api, bundle):
    """Submit, have both parties confirm, and activate at 2026-09-01."""
    validate_success(api.submit_agreement(bundle["agreement_id"], ANALYST_ORIGIN), 200)
    fixtures.verify_policy(api, bundle, bundle["policy_id"])
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    return validate_success(
        api.activate_agreement(bundle["agreement_id"], ANALYST_ORIGIN), 200
    )


class TestAgreementStateOutranksTheFiscalCeiling:
    """A lifecycle check that reads only the note's own status answers before any
    payoff arithmetic is attempted."""

    def test_both_violations_report_the_agreement_state_failure(self, api):
        """A wildly oversized payment on a DRAFT note reports the state failure.

        The PRD states: "A payment on a note that is not `ACTIVE` is refused by
        the agreement-state gate."  A DRAFT note has never had its schedule cut,
        so the payoff figure the fiscal rule needs does not exist.

        Design: Difficulty/priority_pair_validation_conflict/agreement_state_beats_fiscal_overpayment_on_payment
        """
        bundle = _draft_note(api)

        validate_error(
            api.create_payment(
                bundle["agreement_id"],
                factories.payment(999999999, "2026-08-15"),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.AGREEMENT_STATE_INVALID.value,
            409,
        )

    def test_the_state_gate_alone_refuses_a_modest_payment_and_writes_nothing(
        self, api
    ):
        """A perfectly ordinary amount is refused too, and leaves no trace.

        The PRD states: "`DRAFT` accepts policy attachment, submission, voiding
        and rate-exception approval".

        Design: Difficulty/priority_pair_validation_conflict/agreement_state_beats_fiscal_overpayment_on_payment
        """
        bundle = _draft_note(api)
        before = fixtures.read_agreement(api, bundle["agreement_id"])["version"]

        validate_error(
            api.create_payment(
                bundle["agreement_id"],
                factories.payment(999999999, "2026-08-15"),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.AGREEMENT_STATE_INVALID.value,
            409,
        )
        validate_error(
            api.create_payment(
                bundle["agreement_id"],
                factories.payment(50000, "2026-08-15"),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.AGREEMENT_STATE_INVALID.value,
            409,
        )

        rows, meta = validate_paginated(
            api.list_payments(bundle["agreement_id"], ANALYST_ORIGIN, {"limit": 50})
        )
        assert meta["total_count"] == 0, (
            "a refused posting may not leave a Payment row behind"
        )
        assert rows == []
        after = fixtures.read_agreement(api, bundle["agreement_id"])
        assert after["version"] == before, (
            "two refused postings may not advance the note's version"
        )
        assert after["status"] == "DRAFT"

    def test_the_fiscal_ceiling_becomes_reachable_once_the_note_is_active(self, api):
        """The same oversized amount now reports the overpayment ceiling.

        The PRD states: "The platform tolerates a modest overpayment but not an
        arbitrary one: an `amount_cents` exceeding the net payoff by more than
        50000 cents — five hundred dollars — is refused with
        `ERR_PAYMENT_EXCEEDS_PAYOFF` (HTTP 422), where the net payoff is computed
        as of the payment's `received_date`."

        Design: Difficulty/priority_pair_validation_conflict/agreement_state_beats_fiscal_overpayment_on_payment
        """
        bundle = _draft_note(api)
        activated = _activate(api, bundle)

        assert activated["amount_financed_cents"] == 502000
        assert activated["finance_charge_cents"] == 37650
        rebate = rule_of_78_rebate_cents(37650, 6, 6)
        assert rebate == 37650, (
            "with six installments unretired the sum-of-digits rebate returns the "
            "entire finance charge, so the net payoff is the principal alone"
        )

        validate_error(
            api.create_payment(
                bundle["agreement_id"],
                factories.payment(999999999, "2026-09-01"),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.PAYMENT_EXCEEDS_PAYOFF.value,
            422,
        )

    def test_neither_violation_posts_the_payment_through_the_buckets(self, api):
        """An amount inside the ceiling posts and retires finance charge before
        principal.

        The PRD states: "Bucket three does the same for `SCHEDULED` installments
        while any money remains, always taking the lowest `installment_number`
        first and retiring finance charge before principal within each."

        Design: Difficulty/priority_pair_validation_conflict/agreement_state_beats_fiscal_overpayment_on_payment
        """
        bundle = _draft_note(api)
        _activate(api, bundle)

        posted = validate_success(
            api.create_payment(
                bundle["agreement_id"],
                factories.payment(89941, "2026-09-01"),
                ANALYST_ORIGIN,
            ),
            201,
        )

        assert posted["allocation_variant"] == "STANDARD", (
            "89941 is below the net payoff of 502000, and the variant is chosen "
            "before any money moves"
        )
        assert posted["applied_finance_charge_cents"] == 6275
        assert posted["applied_principal_cents"] == 83666
        assert posted["applied_finance_charge_cents"] + posted[
            "applied_principal_cents"
        ] == 89941, "the whole tender is absorbed by the first installment"
        assert posted["rebate_applied_cents"] == 0, (
            "only the payoff variant grants the rebate"
        )

        rows = fixtures.read_installments(api, bundle["agreement_id"])
        rows.sort(key=lambda row: row["installment_number"])
        assert rows[0]["status"] == "PAID", (
            "an installment whose paid_cents reaches its amount_cents moves to PAID"
        )
        assert rows[0]["paid_cents"] == 89941


def _delinquent_note(api):
    """The 600k note carried to LATE with one OUTSTANDING 4497 late fee.

    The clock lands on 2026-10-12, strictly after the 2026-10-01 due date
    advanced by the regime's ten grace days, so the pass both marks the
    installment past due and assesses the fee.
    """
    bundle = fixtures.canonical_600k_note(api, policy_number="MC-R-9201")
    assert bundle["activated"]["principal_balance_cents"] == 502000
    assert bundle["activated"]["unpaid_finance_charge_cents"] == 37650
    assert bundle["activated"]["late_fee_balance_cents"] == 0
    assert bundle["activated"]["unapplied_credit_cents"] == 0
    assert bundle["activated"]["total_of_payments_cents"] == 539650

    report = fixtures.advance_and_service(api, "2026-10-12T00:00:00Z")
    assert report["past_due_marked"] == 1
    assert report["late_fees_assessed"] == 1
    assert report["agreements_advanced_to_late"] == 1

    fees = fixtures.read_late_fees(api, bundle["agreement_id"])
    assert len(fees) == 1
    bundle["fee"] = fees[0]
    bundle["fee_id"] = fees[0]["id"]
    return bundle


def _post_the_cure_tender(api, bundle):
    """Tender 94438 — exactly the fee plus the whole first installment."""
    return validate_success(
        api.create_payment(
            bundle["agreement_id"],
            factories.payment(94438, "2026-10-12"),
            ANALYST_ORIGIN,
        ),
        201,
    )


class TestTotalReceivableAcrossReversalAndWaiver:
    """Two opposite compensations against one note: a reversal that must restore
    the conserved quantity exactly, and a waiver that must reduce it by the fee."""

    def test_the_assessment_raises_the_conserved_quantity_by_exactly_the_fee(
        self, api
    ):
        """Assessing a fee moves total receivable by the fee and nothing else.

        The PRD states: "The first, **total receivable**, is defined as the
        agreement's `principal_balance_cents` plus `unpaid_finance_charge_cents`
        plus `late_fee_balance_cents`, minus `unapplied_credit_cents`."

        Design: Difficulty/compensating_invariant/total_receivable_invariant_across_reversal_and_waiver
        """
        bundle = _delinquent_note(api)
        assert_total_receivable(bundle["activated"], 539650)

        assert bundle["fee"]["amount_cents"] == late_fee_cents(89941, 500, 500, 10000)
        assert bundle["fee"]["amount_cents"] == 4497
        assert bundle["fee"]["status"] == "OUTSTANDING"

        t1 = fixtures.read_agreement(api, bundle["agreement_id"])
        assert t1["principal_balance_cents"] == 502000
        assert t1["unpaid_finance_charge_cents"] == 37650
        assert t1["late_fee_balance_cents"] == 4497
        assert t1["unapplied_credit_cents"] == 0
        assert_total_receivable(t1, 544147)
        assert t1["late_fee_count"] == 1
        assert t1["delinquency_stage"] == "LATE"

    def test_a_standard_posting_reduces_the_quantity_by_exactly_the_cash(self, api):
        """With no unapplied credit the identity falls by exactly the tender.

        The PRD states: "Posting an ordinary payment must reduce total receivable
        by exactly the amount tendered, and reversing a payment must restore total
        receivable to exactly the value it had before that payment was posted,
        together with the `paid_cents` and `status` of every installment the
        payment touched and the status of every late fee it settled."

        Design: Difficulty/compensating_invariant/total_receivable_invariant_across_reversal_and_waiver
        """
        bundle = _delinquent_note(api)
        t1 = fixtures.read_agreement(api, bundle["agreement_id"])

        posted = _post_the_cure_tender(api, bundle)

        assert posted["allocation_variant"] == "STANDARD", (
            "94438 is below the net payoff of 506497, which is 502000 principal "
            "plus 37650 finance charge less a 37650 rebate plus the 4497 fee"
        )
        assert posted["applied_late_fee_cents"] == 4497, (
            "bucket one settles OUTSTANDING late fees first"
        )
        assert posted["applied_finance_charge_cents"] == 6275
        assert posted["applied_principal_cents"] == 83666
        assert posted["applied_unapplied_cents"] == 0
        assert posted["rebate_applied_cents"] == 0
        assert 4497 + 6275 + 83666 == 94438, (
            "the tender exhausts buckets one and two with nothing left to park"
        )

        t2 = fixtures.read_agreement(api, bundle["agreement_id"])
        assert t2["principal_balance_cents"] == 418334
        assert t2["unpaid_finance_charge_cents"] == 31375
        assert t2["late_fee_balance_cents"] == 0
        assert t2["unapplied_credit_cents"] == 0
        assert_total_receivable(t2, 449709)
        assert total_receivable_cents(t2) == total_receivable_cents(t1) - 94438, (
            "the conserved quantity must fall by exactly the amount tendered"
        )
        assert t2["late_fee_count"] == 1, "the lifetime counter is untouched"
        assert t2["delinquency_stage"] == "CURRENT", (
            "the allocation left no PAST_DUE installment and a zero late fee "
            "balance, so the delinquency dimension is cured"
        )
        rows = fixtures.read_installments(api, bundle["agreement_id"])
        rows.sort(key=lambda row: row["installment_number"])
        assert rows[0]["status"] == "PAID"
        assert rows[0]["paid_cents"] == 89941
        fees = fixtures.read_late_fees(api, bundle["agreement_id"])
        assert fees[0]["status"] == "PAID"

    def test_reversal_restores_the_conserved_quantity_with_zero_drift(self, api):
        """The round trip lands byte for byte on the pre-payment ledger.

        The PRD states: "The reversal moves the payment `POSTED` → `REVERSED`,
        stamps `reversed_at` from the logical clock, and unwinds the allocation
        exactly".

        Design: Difficulty/compensating_invariant/total_receivable_invariant_across_reversal_and_waiver
        """
        bundle = _delinquent_note(api)
        t1 = fixtures.read_agreement(api, bundle["agreement_id"])
        posted = _post_the_cure_tender(api, bundle)

        reversed_payment = validate_success(
            api.reverse_payment(posted["id"], factories.reversal(), ANALYST_ORIGIN), 200
        )

        assert reversed_payment["status"] == "REVERSED"
        assert reversed_payment["reversed_at"], (
            "reversed_at is stamped from the logical clock"
        )

        t3 = fixtures.read_agreement(api, bundle["agreement_id"])
        assert t3["principal_balance_cents"] == t1["principal_balance_cents"] == 502000
        assert (
            t3["unpaid_finance_charge_cents"]
            == t1["unpaid_finance_charge_cents"]
            == 37650
        )
        assert t3["late_fee_balance_cents"] == t1["late_fee_balance_cents"] == 4497
        assert t3["unapplied_credit_cents"] == t1["unapplied_credit_cents"] == 0
        assert_total_receivable(t3, 544147)
        assert total_receivable_cents(t3) == total_receivable_cents(t1), (
            "the reversal must restore total receivable to exactly the value it "
            "had before that payment was posted"
        )

    def test_reversal_restores_the_installment_and_the_fee_it_had_settled(self, api):
        """The rows the payment touched are put back as they were.

        The PRD states: "every fee the payment settled returns from `PAID` to
        `OUTSTANDING` and its amount is added back to `late_fee_balance_cents`;
        and every installment the payment touched has its `paid_cents` reduced by
        that payment's contribution, returning to `PAST_DUE` when its `due_date`
        is strictly earlier than the clock date and to `SCHEDULED` otherwise."

        Design: Difficulty/compensating_invariant/total_receivable_invariant_across_reversal_and_waiver
        """
        bundle = _delinquent_note(api)
        posted = _post_the_cure_tender(api, bundle)
        validate_success(
            api.reverse_payment(posted["id"], factories.reversal(), ANALYST_ORIGIN), 200
        )

        rows = fixtures.read_installments(api, bundle["agreement_id"])
        rows.sort(key=lambda row: row["installment_number"])
        assert rows[0]["status"] == "PAST_DUE", (
            "the 2026-10-01 due date is strictly earlier than the clock date of "
            "2026-10-12, so the installment returns to PAST_DUE and not SCHEDULED"
        )
        assert rows[0]["paid_cents"] == 0
        fees = fixtures.read_late_fees(api, bundle["agreement_id"])
        assert fees[0]["status"] == "OUTSTANDING"
        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["delinquency_stage"] == "LATE", (
            "the reversal left a PAST_DUE installment and a positive late fee "
            "balance behind, so the delinquency dimension re-delinquences"
        )

    def test_a_waiver_reduces_the_conserved_quantity_by_exactly_the_fee(self, api):
        """The waiver moves the identity by the fee amount and touches nothing else.

        The PRD states: "The waiver moves the fee `OUTSTANDING` → `WAIVED`,
        records the acting officer in `waived_by_user_id`, decrements the note's
        `late_fee_balance_cents` by the fee amount, and advances both rows'
        `version`."

        Design: Difficulty/compensating_invariant/total_receivable_invariant_across_reversal_and_waiver
        """
        bundle = _delinquent_note(api)
        posted = _post_the_cure_tender(api, bundle)
        validate_success(
            api.reverse_payment(posted["id"], factories.reversal(), ANALYST_ORIGIN), 200
        )

        waived = validate_success(
            api.waive_late_fee(bundle["fee_id"], factories.waiver(), COMPLIANCE_WAIVER),
            200,
        )

        assert waived["status"] == "WAIVED"
        assert waived["waived_by_user_id"] == "compliance-waiver", (
            "the acting compliance officer's opaque operator identifier is recorded"
        )

        t4 = fixtures.read_agreement(api, bundle["agreement_id"])
        assert t4["principal_balance_cents"] == 502000
        assert t4["unpaid_finance_charge_cents"] == 37650
        assert t4["late_fee_balance_cents"] == 0
        assert t4["unapplied_credit_cents"] == 0
        assert_total_receivable(t4, 539650)
        assert total_receivable_cents(t4) == 544147 - 4497, (
            "the waiver moves the conserved quantity by exactly the fee"
        )
        assert t4["delinquency_stage"] == "LATE", (
            "installment 1 is still PAST_DUE, so the waiver alone cannot restore "
            "CURRENT"
        )

    def test_neither_compensation_decrements_the_lifetime_fee_counter(self, api):
        """`late_fee_count` never moves backwards, which is why it is excluded.

        The PRD states: "One counter is deliberately excluded from this identity:
        `late_fee_count` is a lifetime counter that never moves backwards, so
        neither a waiver nor a reversal restores it."

        Design: Difficulty/compensating_invariant/total_receivable_invariant_across_reversal_and_waiver
        """
        bundle = _delinquent_note(api)
        posted = _post_the_cure_tender(api, bundle)
        assert fixtures.read_agreement(api, bundle["agreement_id"])["late_fee_count"] == 1

        validate_success(
            api.reverse_payment(posted["id"], factories.reversal(), ANALYST_ORIGIN), 200
        )
        assert (
            fixtures.read_agreement(api, bundle["agreement_id"])["late_fee_count"] == 1
        ), "the reversal may not give a count back"

        validate_success(
            api.waive_late_fee(bundle["fee_id"], factories.waiver(), COMPLIANCE_WAIVER),
            200,
        )
        assert (
            fixtures.read_agreement(api, bundle["agreement_id"])["late_fee_count"] == 1
        ), "the waiver may not give a count back either"

    def test_a_later_pass_neither_reassesses_nor_moves_the_ledger(self, api):
        """A second servicing pass marks the next installment and charges nothing.

        The PRD states: "And no late fee may already exist for that agreement and
        that `installment_number` unless the existing one is `REVERSED`, so a
        single installment is charged once no matter how many passes run over it".

        Design: Difficulty/compensating_invariant/total_receivable_invariant_across_reversal_and_waiver
        """
        bundle = _delinquent_note(api)
        posted = _post_the_cure_tender(api, bundle)
        validate_success(
            api.reverse_payment(posted["id"], factories.reversal(), ANALYST_ORIGIN), 200
        )
        validate_success(
            api.waive_late_fee(bundle["fee_id"], factories.waiver(), COMPLIANCE_WAIVER),
            200,
        )
        t4 = fixtures.read_agreement(api, bundle["agreement_id"])

        report = fixtures.advance_and_service(api, "2026-11-05T00:00:00Z")

        assert report["past_due_marked"] == 1, (
            "installment 2 was due 2026-11-01 and is now past due"
        )
        assert report["late_fees_assessed"] == 0, (
            "installment 1 already carries a WAIVED fee, which is not REVERSED, "
            "and installment 2 is still inside grace because 2026-11-05 is not "
            "strictly after 2026-11-11"
        )

        t5 = fixtures.read_agreement(api, bundle["agreement_id"])
        assert t5["principal_balance_cents"] == t4["principal_balance_cents"] == 502000
        assert (
            t5["unpaid_finance_charge_cents"]
            == t4["unpaid_finance_charge_cents"]
            == 37650
        )
        assert t5["late_fee_balance_cents"] == 0
        assert t5["unapplied_credit_cents"] == 0
        assert_total_receivable(t5, 539650)
        assert t5["late_fee_count"] == 1
