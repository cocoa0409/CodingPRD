"""Compensating actions must return derived totals to their pre-action values.

Two quantities are conserved. A barge's committed tonnage is physical: clearing a
slot leaves it alone and cancelling the slot returns it to the figure it held
before the order existed, with no clearance residue. The buyer's receivable is
monetary: issuing an invoice books it and voids the buyer's standing, and voiding
the invoice restores both to the cent while pushing the stem back out of settled
receivables into open commitments.
"""

import pytest

from test_helpers import (
    apply_credit_review,
    assert_available_is_limit_less_conservative,
    assert_conservative_is_settled_plus_open,
    build_cleared_order,
    build_confirmed_nomination,
    build_provisional_invoice,
    build_scheduled_order,
    cancel_order,
    clear_order,
    issue_invoice,
    read_asset,
    read_credit_exposure,
    read_customer,
    read_nomination,
    void_invoice,
)

SHRUNK_LIMIT_USD = 941193.73


class TestCommittedTonnageConservation:
    """`committed_quantity_mt` across clear and cancel on one barge."""

    def test_clearance_leaves_the_committed_tonnage_alone(self):
        """PRD §3.5: "The operations desk supplies a `port_clearance_ref`, and the
        order advances `SCHEDULED → CLEARED`, storing that reference and stamping
        `cleared_at` with the current logical clock."
        PRD §3.1: "`committed_quantity_mt` is the sum of `planned_quantity_mt` across
        the asset's delivery orders whose `logistics_status` is `SCHEDULED`, `CLEARED`
        or `PUMPING`, held to three decimals and initialised to 0.000; it is recomputed
        whenever an order enters or leaves that set."

        `SCHEDULED` and `CLEARED` are both inside the committed set, so the forward
        move moves no tonnage.

        Design: Difficulty/compensating_invariant/committed_tonnage_conserved_across_clear_and_cancel
        """
        ctx = build_scheduled_order()
        before = read_asset(ctx)
        assert before["committed_quantity_mt"] == pytest.approx(1200.000, abs=0.0005), (
            "The scheduled slot must already be committed, got "
            f"{before['committed_quantity_mt']}"
        )

        order = clear_order(ctx)

        assert order["logistics_status"] == "CLEARED", (
            f"Expected CLEARED, got {order['logistics_status']}"
        )
        assert order["port_clearance_ref"] == "PA-RTM-0001", (
            f"The clearance reference must be stored, got {order['port_clearance_ref']}"
        )
        assert order["cleared_at"].startswith("2026-08-10T06:30:00"), (
            "cleared_at takes the logical clock at clearance, got "
            f"{order['cleared_at']}"
        )
        after = read_asset(ctx)
        assert after["committed_quantity_mt"] == pytest.approx(1200.000, abs=0.0005), (
            "Clearance moves the order inside the committed set, so the total must "
            f"not change, got {after['committed_quantity_mt']}"
        )

    def test_cancellation_returns_the_barge_to_its_pre_order_tonnage(self):
        """PRD §3.5: "Cancellation always recomputes the asset's
        `committed_quantity_mt`, releasing the order's `planned_quantity_mt`."
        PRD §3.5: "Cancelling an order that had been cleared additionally compensates
        the clearance by clearing `port_clearance_ref` and `cleared_at` back to null."
        PRD §3.1: "`committed_quantity_mt` is the sum of `planned_quantity_mt` across
        the asset's delivery orders whose `logistics_status` is `SCHEDULED`, `CLEARED`
        or `PUMPING`, held to three decimals and initialised to 0.000; it is recomputed
        whenever an order enters or leaves that set."

        Design: Difficulty/compensating_invariant/committed_tonnage_conserved_across_clear_and_cancel
        """
        ctx = build_confirmed_nomination()
        pre_order = read_asset(ctx)["committed_quantity_mt"]
        assert pre_order == pytest.approx(0.000, abs=0.0005), (
            f"A barge with no orders is uncommitted, got {pre_order}"
        )
        build_cleared_order(ctx)

        order = cancel_order(ctx)

        assert order["logistics_status"] == "CANCELLED", (
            f"Expected CANCELLED, got {order['logistics_status']}"
        )
        assert order["port_clearance_ref"] is None, (
            "The compensating move must unwind the clearance reference, got "
            f"{order['port_clearance_ref']}"
        )
        assert order["cleared_at"] is None, (
            f"cleared_at must be unwound to null, got {order['cleared_at']}"
        )
        assert read_asset(ctx)["committed_quantity_mt"] == pytest.approx(
            pre_order, abs=0.0005
        ), (
            "The barge must be back to exactly the tonnage it held before the order "
            f"existed ({pre_order}), got {read_asset(ctx)['committed_quantity_mt']}"
        )

    def test_cancellation_rewinds_the_stem_without_penalising_the_barge(self):
        """PRD §3.5: "And in every case, when no other non-terminal delivery order
        remains on the nomination — that is, when none of its orders is any longer in
        `SCHEDULED`, `CLEARED` or `PUMPING` — the nomination cascades `SCHEDULED →
        AWAITING_SCHEDULE`, incrementing its `version`, so the stem can be
        re-slotted."
        PRD §3.1: "`status` is `AVAILABLE` on registration and becomes `QUARANTINED`
        only through the major-spill cascade described in §3.6."
        PRD §3.1: "`compliance_score` is initialised to 100.00 and is the asset's
        spill-history score, computed as described in §3.6."

        The stem rewinds one step only — not past `CONFIRMED` — and cancelling is not
        a safety event, so the barge stays available with an unblemished score.

        Design: Difficulty/compensating_invariant/committed_tonnage_conserved_across_clear_and_cancel
        """
        ctx = build_cleared_order()
        version_before = read_nomination(ctx)["version"]

        cancel_order(ctx)

        nomination = read_nomination(ctx)
        assert nomination["fulfillment_status"] == "AWAITING_SCHEDULE", (
            "The stem must fall back for re-slotting, got "
            f"{nomination['fulfillment_status']}"
        )
        assert nomination["compliance_status"] == "APPROVED", (
            "The compliance dimension is untouched by a cancellation, got "
            f"{nomination['compliance_status']}"
        )
        assert nomination["version"] == version_before + 1, (
            f"The cascade increments the stem's version once, expected "
            f"{version_before + 1}, got {nomination['version']}"
        )
        asset = read_asset(ctx)
        assert asset["status"] == "AVAILABLE", (
            f"A cancellation must not quarantine the barge, got {asset['status']}"
        )
        assert asset["compliance_score"] == pytest.approx(100.00, abs=0.01), (
            "A cancellation is not a compliance event, so the score stays 100.00, got "
            f"{asset['compliance_score']}"
        )


class TestReceivableConservation:
    """`outstanding_balance_usd` and `credit_status` across issue and void."""

    def _provisional_invoice_against_a_matched_limit(self):
        """A PROVISIONAL 941193.73 invoice on a buyer whose limit is exactly that.

        Shrinking the limit before issuance means utilisation lands on exactly
        1.0000 the moment the receivable is booked.
        """
        ctx = build_provisional_invoice()
        apply_credit_review(ctx, credit_limit_usd=SHRUNK_LIMIT_USD)
        return ctx

    def test_a_provisional_invoice_is_outside_the_settled_input_set(self):
        """PRD §3.2: "The **settled receivables** figure is the sum, rounded to two
        decimal places, of `final_amount_usd` across every invoice belonging to the
        customer whose status is `ISSUED` or `CREDIT_APPLIED`; invoices that are still
        `PROVISIONAL` and invoices that have been made `VOID` are excluded entirely."
        PRD §3.9: "The invoice copies `customer_id` from the nomination behind the
        order and opens in status `PROVISIONAL` with `issued_at` and `due_date` null
        and `claim_credit_usd` at 0.00."

        Design: Difficulty/compensating_invariant/receivable_balance_conserved_across_issue_and_void
        """
        ctx = self._provisional_invoice_against_a_matched_limit()

        customer = read_customer(ctx)
        assert customer["outstanding_balance_usd"] == pytest.approx(0.00, abs=0.01), (
            "An unissued invoice is no receivable, got "
            f"{customer['outstanding_balance_usd']}"
        )
        assert customer["credit_status"] == "OK", (
            f"Utilisation of 0.0000 is OK, got {customer['credit_status']}"
        )
        assert ctx["invoice"]["status"] == "PROVISIONAL", (
            f"Expected PROVISIONAL, got {ctx['invoice']['status']}"
        )

    def test_issuance_books_the_receivable_and_closes_the_stem(self):
        """PRD §3.9: "Issuance stamps `issued_at` with the logical clock and derives
        `due_date` as `issued_at` plus the customer's `payment_terms_days` days. It
        then recomputes the customer's `outstanding_balance_usd`, which itself cascades
        a re-derivation of the customer's `credit_status`, and cascades the nomination
        `DELIVERED → CLOSED` on its fulfilment dimension."
        PRD §3.2: "When utilisation is at least 1.0000 the `credit_status` becomes
        `HOLD`; when it is at least 0.8000 but below 1.0000 it becomes `WATCH`;
        otherwise it is `OK`."

        A 941193.73 receivable against a 941193.73 limit is utilisation of exactly
        1.0000, and the 30-day terms put the due date 30 days after 14:30 on the 10th.

        Design: Difficulty/compensating_invariant/receivable_balance_conserved_across_issue_and_void
        """
        ctx = self._provisional_invoice_against_a_matched_limit()

        invoice = issue_invoice(ctx)

        assert invoice["status"] == "ISSUED", (
            f"Expected ISSUED, got {invoice['status']}"
        )
        assert invoice["issued_at"].startswith("2026-08-10T14:30:00"), (
            f"issued_at takes the logical clock, got {invoice['issued_at']}"
        )
        assert invoice["due_date"].startswith("2026-09-09T14:30:00"), (
            "30 payment-terms days after 2026-08-10T14:30:00Z is 2026-09-09T14:30:00Z, "
            f"got {invoice['due_date']}"
        )
        customer = read_customer(ctx)
        assert customer["outstanding_balance_usd"] == pytest.approx(
            SHRUNK_LIMIT_USD, abs=0.01
        ), (
            "The whole invoice must land on the books, got "
            f"{customer['outstanding_balance_usd']}"
        )
        assert customer["credit_status"] == "HOLD", (
            f"Utilisation of exactly 1.0000 is a hold, got {customer['credit_status']}"
        )
        assert read_nomination(ctx)["fulfillment_status"] == "CLOSED", (
            "Issuance closes the stem, got "
            f"{read_nomination(ctx)['fulfillment_status']}"
        )

    def test_voiding_restores_the_pre_issue_receivable_and_standing(self):
        """PRD §3.9: "Voiding an invoice in `ISSUED` moves it to `VOID`, recomputes
        the customer's `outstanding_balance_usd` to remove the receivable and
        re-derives `credit_status`, and cascades the nomination `CLOSED → DELIVERED`
        so the stem can be re-billed; that reopening applies when the voided invoice
        was the only invoice in `ISSUED` or `CREDIT_APPLIED` status on the
        nomination's delivered order."
        PRD §3.9: "`final_amount_usd` is `provisional_amount_usd` minus
        `claim_credit_usd`, rounded to two decimal places."

        Design: Difficulty/compensating_invariant/receivable_balance_conserved_across_issue_and_void
        """
        ctx = self._provisional_invoice_against_a_matched_limit()
        issue_invoice(ctx)

        invoice = void_invoice(ctx)

        assert invoice["status"] == "VOID", (
            f"Expected VOID, got {invoice['status']}"
        )
        assert invoice["final_amount_usd"] == pytest.approx(SHRUNK_LIMIT_USD, abs=0.01), (
            "The voided row keeps its own amount, got "
            f"{invoice['final_amount_usd']}"
        )
        customer = read_customer(ctx)
        assert customer["outstanding_balance_usd"] == pytest.approx(0.00, abs=0.01), (
            "The compensating move must remove the receivable to the cent, got "
            f"{customer['outstanding_balance_usd']}"
        )
        assert customer["credit_status"] == "OK", (
            "With nothing settled the standing must return to OK, got "
            f"{customer['credit_status']}"
        )
        assert read_nomination(ctx)["fulfillment_status"] == "DELIVERED", (
            "The stem must reopen for re-billing, got "
            f"{read_nomination(ctx)['fulfillment_status']}"
        )

    def test_the_voided_stem_moves_back_into_open_commitments(self):
        """PRD §3.2: "Its input set is the customer's nominations whose
        `fulfillment_status` is `CONFIRMED`, `SCHEDULED`, `AWAITING_SCHEDULE` or
        `DELIVERED` and for which no delivery order carries an invoice in status
        `ISSUED` or `CREDIT_APPLIED`; nominations still in `DRAFT` and nominations
        already `CLOSED` are excluded."
        PRD §3.2: "Each qualifying nomination is valued at its
        `nominated_quantity_mt` multiplied by the governing index price of its grade
        at the current logical clock, and the sum is rounded to two decimal places."
        PRD §3.2: "The **conservative exposure** written to
        `conservative_exposure_usd` is the settled receivables plus the open
        commitments, rounded to two decimal places"

        1200.000 nominated tonnes at the 745.50 quote governing on the 10th is
        894600.00, so the same stem that was 941193.73 of settled receivable becomes
        894600.00 of open commitment.

        Design: Difficulty/compensating_invariant/receivable_balance_conserved_across_issue_and_void
        """
        ctx = self._provisional_invoice_against_a_matched_limit()
        issue_invoice(ctx)
        booked = read_credit_exposure(ctx)
        assert booked["open_commitment_count"] == 0, (
            "A CLOSED stem is outside the commitment set, got "
            f"{booked['open_commitment_count']}"
        )

        void_invoice(ctx)

        exposure = read_credit_exposure(ctx)
        assert exposure["open_commitment_count"] == 1, (
            "The reopened stem must re-enter the commitment set, got "
            f"{exposure['open_commitment_count']}"
        )
        assert exposure["conservative_exposure_usd"] == pytest.approx(
            894600.00, abs=0.01
        ), (
            "1200.000 mt at 745.50 with nothing settled is 894600.00, got "
            f"{exposure['conservative_exposure_usd']}"
        )
        assert exposure["outstanding_balance_usd"] == pytest.approx(0.00, abs=0.01), (
            "Nothing is settled any longer, got "
            f"{exposure['outstanding_balance_usd']}"
        )
        assert_conservative_is_settled_plus_open(exposure, 894600.00)
        assert_available_is_limit_less_conservative(exposure)
        assert exposure["available_credit_usd"] == pytest.approx(46593.73, abs=0.01), (
            "941193.73 less 894600.00 is 46593.73, got "
            f"{exposure['available_credit_usd']}"
        )
