"""Compensating pairs on the two append-only ledgers."""

import pytest
from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions, factories, fixtures, make_bursar_headers, make_partner_account_lead_headers


class TestPaymentThenEqualRefundConservesCash:
    @pytest.fixture
    def paid_enrollment(self, api):
        """One ACTIVE enrollment paid 562,500 cents in full on 2026-09-05."""
        return fixtures.build_paid_enrollment(api)

    def test_the_compensating_refund_is_recorded_as_a_manual_bursar_entry(
        self, api, paid_enrollment
    ):
        """The reversal is an ordinary hand-posted REFUND, not a cascade-generated one.

        PRD: "Entries carry a `generated_by` marker that the server sets: `BURSAR_POST` for an
        entry a bursar posts by hand, and `WITHDRAWAL_REFUND` for the compensating entry the
        withdrawal cascade creates on its own."
        PRD: "A manual `REFUND` may not exceed what remains collected — its `amount_cents` must be
        no greater than the enrollment's `collected_cents` less its `refunded_cents` — and an
        over-refund is refused with `ERR_REFUND_EXCEEDS_COLLECTED`."

        Design: Difficulty/compensating_invariant/payment_then_equal_refund_conserves_partnership_cash_collected
        """
        response = api.create_tuition_payment(
            paid_enrollment["en_id"],
            factories.tuition_payment_payload(
                entry_type="REFUND",
                amount_cents=562500,
                reference_note="Full reversal of duplicate posting",
            ),
            headers=make_bursar_headers(),
        )
        entry = validate_success(response, 201)

        assert entry["entry_type"] == "REFUND"
        assert entry["amount_cents"] == 562500
        assert entry["generated_by"] == "BURSAR_POST"

    def test_equal_and_opposite_entries_return_the_partnership_cash_to_zero(
        self, api, paid_enrollment
    ):
        """Gross histories both stand at 562,500 while the net position is back to nothing.

        PRD: "The consequence is a compensating-action guarantee: a `PAYMENT` of some amount
        followed by a `REFUND` of the same amount on the same enrollment must leave
        `collected_tuition_cents` at exactly its pre-payment value, and must leave the
        enrollment's collected-minus-refunded difference at exactly its pre-payment value. No
        intermediate cascade — the enrollment flipping to `ACTIVE`, a statement being staled, a
        counselor clawback accruing — may leave any drift behind."

        Design: Difficulty/compensating_invariant/payment_then_equal_refund_conserves_partnership_cash_collected
        """
        context = paid_enrollment
        fixtures.post_tuition_entry(
            api,
            context["en_id"],
            entry_type="REFUND",
            amount_cents=562500,
            reference_note="Full reversal of duplicate posting",
        )

        enrollment = fixtures.read_enrollment(api, context["en_id"])
        assert enrollment["collected_cents"] == 562500
        assert enrollment["refunded_cents"] == 562500
        assert enrollment["status"] == "ACTIVE"

        partnership = fixtures.read_partnership(api, context["ps_id"])
        assert partnership["collected_tuition_cents"] == 0
        assertions.assert_enrollment_cash_position(enrollment, 562500, 562500)
        assertions.assert_cash_position(partnership, 562500, 562500)

        assert fixtures.read_counselor(api, context["co_id"])["clawback_pending_cents"] == 0


class TestSpendThenEqualCreditMemoConservesTheEnvelope:
    @pytest.fixture
    def launched_program_with_untouched_envelope(self, api):
        """A LAUNCHED program with no media posted yet, clock at 2026-09-05."""
        context = fixtures.build_launched_program(api, with_counselor=False)
        fixtures.set_clock(api, fixtures.CLOCK_SEP_5)
        return context

    def test_the_credit_memo_is_recorded_against_the_same_program_ledger(
        self, api, launched_program_with_untouched_envelope
    ):
        """A credit memo carries its own direction and a mandatory reversal note.

        PRD: "An entry names its `program_id`, an `entry_type` of `SPEND` or `CREDIT_MEMO`, a
        `channel` of `PAID_SEARCH`, `PAID_SOCIAL`, `DISPLAY`, `EVENTS` or `LIST_PURCHASE`, a
        positive `amount_cents` whose direction is carried entirely by `entry_type`, and a
        `spend_date` on which the amount is recognised in the marketing ledger. A
        `reversal_note` is a free-text explanation and is required on a `CREDIT_MEMO` entry."

        Design: Difficulty/compensating_invariant/spend_then_equal_credit_memo_conserves_the_marketing_budget_envelope
        """
        context = launched_program_with_untouched_envelope
        fixtures.post_marketing_entry(api, context["ps_id"], context["pg_id"], amount_cents=300000)

        response = api.create_marketing_spend_entry(
            context["pg_id"],
            factories.marketing_spend_payload(
                entry_type="CREDIT_MEMO",
                amount_cents=300000,
                reversal_note="Agency credit for undelivered impressions",
            ),
            headers=make_partner_account_lead_headers(context["ps_id"]),
        )
        entry = validate_success(response, 201)

        assert entry["entry_type"] == "CREDIT_MEMO"
        assert entry["amount_cents"] == 300000

    def test_the_pair_restores_the_full_envelope_and_the_program_net(
        self, api, launched_program_with_untouched_envelope
    ):
        """The envelope identity holds after the reversal, with nothing left unrecouped.

        PRD: "The identity that the budget equals the remaining budget plus posted net spend
        holds after every write, and a `SPEND` of some amount followed by a `CREDIT_MEMO` of the
        same amount on the same program restores `marketing_budget_remaining_cents` to exactly
        `marketing_budget_cents` and restores the program's `marketing_spend_net_cents` to its
        pre-spend value."
        PRD: "When `total_enrollment_count` is zero the value is null — never 0 — because dividing
        spend by no enrollments has no meaning, and the distinction between "no students yet" and
        "free students" must survive into the response."

        Design: Difficulty/compensating_invariant/spend_then_equal_credit_memo_conserves_the_marketing_budget_envelope
        """
        context = launched_program_with_untouched_envelope
        fixtures.post_marketing_entry(api, context["ps_id"], context["pg_id"], amount_cents=300000)
        fixtures.post_marketing_entry(
            api,
            context["ps_id"],
            context["pg_id"],
            entry_type="CREDIT_MEMO",
            amount_cents=300000,
            reversal_note="Agency credit for undelivered impressions",
        )

        program = fixtures.read_program(api, context["pg_id"])
        assert program["marketing_spend_net_cents"] == 0
        assert program["blended_cac_cents"] is None

        partnership = fixtures.read_partnership(api, context["ps_id"])
        assert partnership["marketing_budget_remaining_cents"] == 4000000
        assert partnership["unrecouped_marketing_spend_cents"] == 0
        assertions.assert_marketing_envelope(partnership, program["marketing_spend_net_cents"])
