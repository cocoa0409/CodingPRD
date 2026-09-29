"""Two state machines that are not walks along a line.

A credit leaves `ISSUED` for `AMENDMENT_PENDING` and comes back twice, and the same edge
produces opposite outcomes on the two traversals. A presentation carries two dimensions
at once, and the settlement dimension advances while the examination dimension stands
still. Neither shape can be produced by a single linear path.
"""

from test_helpers import (
    assert_end_of_day_instant,
    assert_facility_ledger,
    complying_presentation,
    consent_to_amendment,
    draft_amendment,
    issue_amendment,
    issued_credit,
    lodge_claim,
    set_clock,
    settle_claim,
    setup_parties,
)


def _issued_ten_million(parties=None):
    return issued_credit(
        parties or setup_parties(facility={"limit_cents": 50000000}),
        amount_cents=10000000,
        available_by="SIGHT_PAYMENT",
        tenor_days=0,
        tolerance_pct=0,
        latest_shipment_date="2026-10-31",
        expiry_date="2026-11-30",
        presentation_period_days=21,
    )


class TestCreditAmendmentCycleReturnsToIssuedTwice:
    """Round one is rejected on its original terms; round two is accepted and applied."""

    def _two_rounds(self):
        ctx = _issued_ten_million()
        first = draft_amendment(ctx, {"expiry_date": "2026-11-15"})
        issue_amendment(first["id"])
        set_clock("2026-08-12T09:00:00Z")
        consent_to_amendment(first["id"], ctx.parties.beneficiary_id, "REJECT")
        set_clock("2026-08-15T09:00:00Z")
        second = draft_amendment(ctx, {"presentation_period_days": 15})
        issued_second = issue_amendment(second["id"])
        set_clock("2026-08-16T09:00:00Z")
        accepted = consent_to_amendment(
            second["id"], ctx.parties.beneficiary_id, "ACCEPT"
        )
        return ctx, first, issued_second, accepted

    def test_rejection_returns_the_credit_to_issued_on_its_original_terms(self, clock):
        """The first traversal of the edge leaves every credit field untouched.

        PRD 3.5: "`REJECT` moves `PENDING_CONSENT → REJECTED`, sets `resolved_at` to the
        clock instant and `window_end_effective` to the clock date, returns the credit
        `AMENDMENT_PENDING → ISSUED` on its original terms, and sets
        `amendment_fee_cents` to 0 — no fee is charged for a rejected amendment."

        Design: Difficulty/non_linear_state_machine/credit_amendment_cycle_returns_to_issued_twice
        """
        ctx = _issued_ten_million()
        first = draft_amendment(ctx, {"expiry_date": "2026-11-15"})
        issue_amendment(first["id"])
        assert ctx.refresh()["status"] == "AMENDMENT_PENDING"
        set_clock("2026-08-12T09:00:00Z")

        rejected = consent_to_amendment(first["id"], ctx.parties.beneficiary_id, "REJECT")

        assert rejected["seq"] == 1
        assert rejected["status"] == "REJECTED"
        assert rejected["window_end_effective"] == "2026-08-12"
        credit = ctx.refresh()
        assert credit["status"] == "ISSUED"
        assert credit["expiry_date"] == "2026-11-30"
        assert credit["amendment_seq"] == 0

    def test_acceptance_on_the_second_round_applies_the_change_set(self, clock):
        """The second traversal of the same edge does apply the change and renumbers.

        PRD 3.5: "Hop one applies the `change_set` to the credit, sets the credit's
        `amendment_seq` to this amendment's `seq`, and returns the credit
        `AMENDMENT_PENDING → ISSUED`."

        Design: Difficulty/non_linear_state_machine/credit_amendment_cycle_returns_to_issued_twice
        """
        ctx, first, issued_second, accepted = self._two_rounds()

        assert accepted["seq"] == 2
        assert accepted["seq"] - first["seq"] == 1
        assert accepted["status"] == "ACCEPTED"
        credit = ctx.refresh()
        assert credit["status"] == "ISSUED"
        assert credit["expiry_date"] == "2026-11-30"
        assert credit["presentation_period_days"] == 15
        assert credit["presentation_deadline_date"] == "2026-11-15"
        assert credit["amendment_seq"] == 2
        assert credit["committed_allocation_cents"] == 10000000

    def test_the_second_window_and_its_flat_fee_are_priced_at_issuance(self, clock):
        """The consent window opens on the issue date and a zero delta pays the flat fee.

        PRD 3.5: "When `exposure_delta_cents` is zero or negative, `amendment_fee_cents` is
        the flat 7,500 cents."

        Design: Difficulty/non_linear_state_machine/credit_amendment_cycle_returns_to_issued_twice
        """
        ctx, _first, issued_second, accepted = self._two_rounds()

        assert issued_second["requires_beneficiary_consent"] is True
        assert issued_second["consent_window_start"] == "2026-08-15"
        assert issued_second["consent_deadline_date"] == "2026-08-25"
        assert accepted["exposure_delta_cents"] == 0
        assert accepted["amendment_fee_cents"] == 7500
        assert_facility_ledger(
            ctx.refresh_facility(),
            allocated_cents=10032500,
            available_cents=39967500,
        )


class TestPresentationParallelExaminationAndSettlementDimensions:
    """Money moves through three settlement edges while the examination verdict stands."""

    def _complying_file(self):
        ctx = _issued_ten_million()
        set_clock("2026-09-14T09:00:00Z")
        return complying_presentation(ctx, (4000000,))

    def test_settlement_advances_while_the_examination_verdict_stays_complying(self, clock):
        """Claiming and settling never re-open the examination dimension.

        PRD 3.6: "Submission, examination and waiver handling move `examination_status`
        while `settlement_status` stays pinned at `UNSETTLED`; claiming and settling move
        `settlement_status` while `examination_status` stays pinned at `COMPLYING` or
        `PRECLUDED`."

        Design: Difficulty/non_linear_state_machine/presentation_parallel_examination_and_settlement_dimensions
        """
        pctx = self._complying_file()
        assert pctx.presentation["examination_status"] == "COMPLYING"
        assert pctx.presentation["settlement_status"] == "UNSETTLED"

        claim = lodge_claim(pctx, "PAYMENT", 4000000)
        midway = pctx.refresh()
        assert midway["examination_status"] == "COMPLYING"
        assert midway["settlement_status"] == "CLAIM_LODGED"

        settle_claim(claim["id"])

        final = pctx.refresh()
        assert final["examination_status"] == "COMPLYING"
        assert final["settlement_status"] == "PAID"
        assert final["discrepancy_count"] == 0
        assert final["refusal_notice_sent_at"] is None
        assert final["disposal_instruction"] is None

    def test_the_examination_deadline_and_the_frozen_drawing_survive_settlement(self, clock):
        """The deadline instant and the frozen drawn amount are unchanged by the payout.

        PRD 3.6: "`drawn_amount_cents` becomes the sum of `invoice_amount_cents` over the
        file's `COMMERCIAL_INVOICE` documents and is never re-summed afterwards, and
        `document_count` is likewise frozen."

        Design: Difficulty/non_linear_state_machine/presentation_parallel_examination_and_settlement_dimensions
        """
        pctx = self._complying_file()
        assert_end_of_day_instant(
            pctx.presentation["examination_deadline"], "2026-09-21", "examination_deadline"
        )

        settled = settle_claim(lodge_claim(pctx, "PAYMENT", 4000000)["id"])

        assert settled["commission_cents"] == 4800
        assert settled["doc_examination_fee_cents"] == 5500
        assert settled["net_proceeds_cents"] == 3989700
        assert pctx.refresh()["drawn_amount_cents"] == 4000000

    def test_a_sight_payout_moves_the_drawing_from_reserved_to_settled(self, clock):
        """The credit's own ledger records the payout without leaving `ISSUED`.

        PRD 3.9: "A sight honour on a `PAYMENT` claim moves `CLAIM_LODGED → PAID`, and the
        drawing moves out of the credit's `reserved_cents` into its `drawn_settled_cents`
        — both by exactly `drawn_amount_cents`, so `available_cents` is unchanged by
        settlement."

        Design: Difficulty/non_linear_state_machine/presentation_parallel_examination_and_settlement_dimensions
        """
        pctx = self._complying_file()
        assert pctx.refresh_credit()["reserved_cents"] == 4000000

        settle_claim(lodge_claim(pctx, "PAYMENT", 4000000)["id"])

        credit = pctx.refresh_credit()
        assert credit["reserved_cents"] == 0
        assert credit["drawn_settled_cents"] == 4000000
        assert credit["available_cents"] == 6000000
        assert credit["status"] == "ISSUED"
