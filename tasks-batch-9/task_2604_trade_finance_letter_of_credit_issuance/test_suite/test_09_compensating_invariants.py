"""Two ledgers driven away from their starting value and then driven back to it exactly.

Issuing a credit and cancelling it must return the facility's `allocated_cents` to the cent,
along with the posture, the status, the suspension reason and the two siblings the
suspension parked. Submitting two presentations and refusing both must return the credit's
`available_cents` to the cent, while the facility ledger never moves at all.
"""

from test_helpers import (
    approved_credit,
    assert_conserved,
    assert_facility_ledger,
    cancel_credit,
    discrepant_presentation,
    issue_credit,
    issued_credit,
    list_credit_allocation_rows,
    refuse_presentation,
    set_clock,
    setup_parties,
)

SIGHT_TERMS = {
    "available_by": "SIGHT_PAYMENT",
    "tenor_days": 0,
    "tolerance_pct": 0,
    "presentation_period_days": 21,
}


class TestFacilityAllocatedCentsConservedAcrossIssueThenCancel:
    """A 95,066,500 allocation raised and released on a 100,000,000 facility."""

    def _three_credits_one_issued(self):
        parties = setup_parties(facility={"limit_cents": 100000000})
        terms = dict(
            SIGHT_TERMS,
            latest_shipment_date="2026-09-14",
            expiry_date="2026-10-05",
        )
        first = approved_credit(parties, None, amount_cents=95000000, **terms)
        second = approved_credit(parties, None, amount_cents=1000000, **terms)
        third = approved_credit(parties, None, amount_cents=2000000, **terms)
        allocated_before = parties.refresh_facility()["allocated_cents"]
        issue_credit(first.credit_id)
        first.refresh()
        return parties, allocated_before, first, second, third

    def test_the_issuance_peak_is_the_full_chargeable_utilisation(self, clock):
        """The quantity to be conserved is first driven to 95,066,500 from zero.

        PRD 3.3: "**Hop two** is caused by hop one: the new open row re-drives the facility's
        exposure ledger, so the facility's `allocated_cents` rises by exactly the credit's
        `chargeable_utilisation_cents`, its `available_cents` falls by the same amount, and
        its `version` increments by one."

        Design: Difficulty/compensating_invariant/facility_allocated_cents_conserved_across_issue_then_cancel
        """
        parties, allocated_before, first, second, third = self._three_credits_one_issued()

        assert allocated_before == 0
        assert parties.refresh_facility()["allocated_cents"] == 95066500
        assert first.credit["committed_allocation_cents"] == 95000000
        assert first.credit["base_commission_cents"] == 66500
        assert first.credit["chargeable_utilisation_cents"] == 95066500
        assert second.refresh()["status"] == "ON_HOLD"
        assert third.refresh()["status"] == "ON_HOLD"

    def test_cancellation_releases_the_row_for_its_allocation_plus_its_charges(self, clock):
        """The released amount is the row's own allocation plus its own charge, not the gross.

        PRD 3.3: "Every `OPEN` allocation row of the credit flips to `RELEASED` with
        `released_cents` set to that row's own `allocated_cents` plus its `charge_cents` and
        `released_at` set to the clock instant, and the row's `version` increments."

        Design: Difficulty/compensating_invariant/facility_allocated_cents_conserved_across_issue_then_cancel
        """
        _parties, _before, first, _second, _third = self._three_credits_one_issued()

        cancelled = cancel_credit(
            first.credit_id, beneficiary_consent_reference="BEN-CONSENT-2026-0001"
        )

        assert cancelled["status"] == "CANCELLED"
        rows = list_credit_allocation_rows(first.credit_id)
        assert len(rows) == 1
        assert rows[0]["status"] == "RELEASED"
        assert rows[0]["released_cents"] == 95066500
        assert rows[0]["released_at"] is not None

    def test_every_side_effect_of_the_issuance_is_reversed_to_the_cent(self, clock):
        """The ledger, the posture, the status, the reason and both siblings all come back.

        PRD 3.1: "The reverse is symmetric: when a recomputation leaves `allocated_cents`
        strictly below `restrict_threshold_cents` on a facility that is `SUSPENDED` for
        reason `RESTRICT_THRESHOLD_BREACH`, the facility returns `SUSPENDED → ACTIVE`,
        `suspended_reason` is cleared to unset, `utilisation_posture` returns to `OPEN`, and
        every `ON_HOLD` credit on that facility returns to `APPROVED` in `created_at`
        ascending order."

        Design: Difficulty/compensating_invariant/facility_allocated_cents_conserved_across_issue_then_cancel
        """
        parties, allocated_before, first, second, third = self._three_credits_one_issued()

        cancel_credit(
            first.credit_id, beneficiary_consent_reference="BEN-CONSENT-2026-0001"
        )

        facility = parties.refresh_facility()
        assert_conserved(allocated_before, facility["allocated_cents"], "allocated_cents")
        assert_facility_ledger(
            facility,
            allocated_cents=0,
            available_cents=100000000,
            restrict_threshold_cents=95000000,
            utilisation_posture="OPEN",
            status="ACTIVE",
            suspended_reason=None,
        )
        assert second.refresh()["status"] == "APPROVED"
        assert third.refresh()["status"] == "APPROVED"


class TestCreditAvailableCentsConservedAcrossTwoPresentationsAndRefusals:
    """Two drawings reserved in turn and both walked back out of the credit's ledger."""

    def _issued_ten_million(self):
        return issued_credit(
            setup_parties(facility={"limit_cents": 50000000}),
            None,
            amount_cents=10000000,
            latest_shipment_date="2026-10-31",
            expiry_date="2026-11-30",
            **SIGHT_TERMS,
        )

    def _two_discrepant_files(self, ctx):
        set_clock("2026-09-14T09:00:00Z")
        first = discrepant_presentation(
            ctx, "GOODS_DESCRIPTION_MISMATCH", "MATERIAL", (2000000,)
        )
        second = discrepant_presentation(
            ctx, "GOODS_DESCRIPTION_MISMATCH", "MATERIAL", (3000000,)
        )
        return first, second

    def test_two_submissions_reserve_their_drawings_cumulatively(self, clock):
        """`available_cents` walks 10,000,000 to 8,000,000 to 5,000,000 as each file freezes.

        PRD 3.6: "`drawn_amount_cents` becomes the sum of `invoice_amount_cents` over the
        file's `COMMERCIAL_INVOICE` documents and is never re-summed afterwards, and
        `document_count` is likewise frozen."

        Design: Difficulty/compensating_invariant/credit_available_cents_conserved_across_two_presentations_and_refusals
        """
        ctx = self._issued_ten_million()
        assert ctx.credit["available_cents"] == 10000000

        set_clock("2026-09-14T09:00:00Z")
        first = discrepant_presentation(
            ctx, "GOODS_DESCRIPTION_MISMATCH", "MATERIAL", (2000000,)
        )
        assert first.presentation["drawn_amount_cents"] == 2000000
        assert ctx.refresh()["available_cents"] == 8000000

        second = discrepant_presentation(
            ctx, "GOODS_DESCRIPTION_MISMATCH", "MATERIAL", (3000000,)
        )
        assert second.presentation["drawn_amount_cents"] == 3000000
        assert ctx.refresh()["available_cents"] == 5000000

    def test_the_two_refusals_unwind_the_ledger_step_by_step(self, clock):
        """Each refusal returns exactly its own drawing, landing back on 10,000,000.

        PRD 2.6: "This is what makes the conservation property hold to the cent: releasing
        an allocation restores the facility to exactly the value it held before that
        allocation was opened, and voiding a drawing restores the credit to exactly its
        pre-submission drawable position."

        Design: Difficulty/compensating_invariant/credit_available_cents_conserved_across_two_presentations_and_refusals
        """
        ctx = self._issued_ten_million()
        available_at_start = ctx.credit["available_cents"]
        first, second = self._two_discrepant_files(ctx)
        assert ctx.refresh()["available_cents"] == 5000000

        refuse_presentation(first, "RETURN_TO_PRESENTER")
        assert ctx.refresh()["available_cents"] == 7000000
        refuse_presentation(second, "RETURN_TO_PRESENTER")

        credit = ctx.refresh()
        assert_conserved(available_at_start, credit["available_cents"], "available_cents")
        assert credit["available_cents"] == 10000000
        assert credit["reserved_cents"] == 0
        assert credit["drawn_settled_cents"] == 0
        assert credit["max_drawable_cents"] == 10000000
        assert first.refresh()["examination_status"] == "REFUSED"
        assert first.presentation["settlement_status"] == "VOID"
        assert second.refresh()["examination_status"] == "REFUSED"
        assert second.presentation["settlement_status"] == "VOID"

    def test_the_facility_ledger_is_pinned_throughout_the_whole_cycle(self, clock):
        """Drawings and refusals are credit-level events; facility exposure never moves.

        PRD 3.7: "The facility is deliberately untouched: `allocated_cents` does not move,
        because facility exposure is committed at issuance and not at drawing, and the
        credit itself remains outstanding."

        Design: Difficulty/compensating_invariant/credit_available_cents_conserved_across_two_presentations_and_refusals
        """
        ctx = self._issued_ten_million()
        first, second = self._two_discrepant_files(ctx)
        allocated_with_drawings_live = ctx.refresh_facility()["allocated_cents"]

        refuse_presentation(first, "RETURN_TO_PRESENTER")
        refuse_presentation(second, "RETURN_TO_PRESENTER")

        allocated_after = ctx.refresh_facility()["allocated_cents"]
        assert allocated_with_drawings_live == 10025000
        assert_conserved(
            allocated_with_drawings_live, allocated_after, "facility allocated_cents"
        )
        assert ctx.refresh()["chargeable_utilisation_cents"] == 10025000
