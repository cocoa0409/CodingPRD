"""
Compensating transitions that exist to conserve a quantity: voiding a receipt
against the bushel obligation, and releasing a lien against a credit line.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers.assertions import assert_fields_equal


class TestObligationBushelsConservedAcrossIssueAndVoid:
    @pytest.fixture
    def voidable_receipt(self, base_full, set_clock):
        """A day-old receipt, still comfortably inside the 72-hour void window."""
        set_clock("2026-08-06T08:00:00Z")
        return base_full

    def test_the_total_obligation_is_identical_before_and_after_the_void(
        self, api, voidable_receipt
    ):
        """
        The receipted side carries all 949 bushels while the receipt stands and
        none of them once it is voided, yet the total the warehouse owes never
        moves: the same bushels simply return to the unreceipted side.

        PRD: "The warehouse's total obligation before and after a void is
        therefore identical, while its receipted obligation falls — that pairing
        is the whole point of the transition."

        Design: Difficulty/compensating_invariant/obligation_bushels_conserved_across_receipt_issue_and_void
        """
        scenario = voidable_receipt
        headers = scenario["operator_headers"]

        before = get_success_data(
            api.get_warehouse(scenario["warehouse_id"], headers), 200
        )
        assert_fields_equal(
            before,
            {"obligation_bushels": 949, "receipted_obligation_bushels": 949},
        )

        get_success_data(
            api.void_receipt(scenario["receipt_id"], f.void_payload(), headers), 200
        )

        after = get_success_data(
            api.get_warehouse(scenario["warehouse_id"], headers), 200
        )
        assert_fields_equal(
            after,
            {
                "obligation_bushels": 949,
                "receipted_obligation_bushels": 0,
                "position_variance_bushels": 0,
                "operational_posture": "OPEN",
            },
        )

    def test_the_void_zeroes_the_receipt_restores_the_ticket_and_moves_no_grain(
        self, api, voidable_receipt
    ):
        """
        The compensating move is visible on all three rows at once: the receipt
        is VOIDED with its quantity zeroed, the source ticket is back to
        ACCEPTED, and the bin still physically holds the 949 bushels it held
        before.

        PRD: "A void moves `receipt_state` to `VOIDED`, zeroes
        `quantity_bushels`, and thereby removes the receipt from the warehouse's
        `receipted_obligation_bushels`; returns the source deposit ticket from
        `RECEIPTED` back to `ACCEPTED`, so the very same bushels re-enter
        `obligation_bushels` as unreceipted stock; and leaves the bin's
        `stored_bushels` completely unchanged, because voiding a receipt does not
        move grain."

        Design: Difficulty/compensating_invariant/obligation_bushels_conserved_across_receipt_issue_and_void
        """
        scenario = voidable_receipt
        headers = scenario["operator_headers"]

        receipt = get_success_data(
            api.void_receipt(scenario["receipt_id"], f.void_payload(), headers), 200
        )
        assert_fields_equal(
            receipt, {"receipt_state": "VOIDED", "quantity_bushels": 0}
        )

        ticket = get_success_data(
            api.get_deposit_ticket(scenario["ticket_id"], headers), 200
        )
        assert ticket["ticket_state"] == "ACCEPTED"

        storage_bin = get_success_data(api.get_bin(scenario["bin_id"], headers), 200)
        assert storage_bin["stored_bushels"] == 949


class TestLenderCreditLineConservedAcrossPerfectAndRelease:
    @pytest.fixture
    def requested_lien(self, api, base_full, set_clock):
        """A recorded but unperfected mark-to-market advance of 250000 cents."""
        set_clock("2026-08-20T09:00:00Z")
        lien = get_success_data(
            api.create_collateral_lien(
                f.collateral_lien_payload(
                    base_full["receipt_id"], base_full["lender_id"]
                ),
                base_full["lender_headers"],
            ),
            201,
        )
        return lien["id"]

    def test_perfection_charges_the_advance_limit_against_an_untouched_line(
        self, api, base_full, requested_lien
    ):
        """
        While the request merely sits recorded the whole 50000000-cent line is
        available; perfection charges exactly the lien's 290482-cent advance
        limit against it, leaving 49709518.

        PRD: "Perfection re-runs the whole seven-step valuation at the current
        logical clock — which matters, because the provisional storage charge
        inside the warehouseman lien has grown since the request was recorded —
        then sets `perfected_at`, moves `lien_state` to `PERFECTED`, drives the
        receipt's `encumbrance_state` to `PLEDGED`, and raises the lender's
        `committed_advance_cents` by `advance_limit_cents`."

        Design: Difficulty/compensating_invariant/lender_credit_line_conserved_across_lien_perfect_and_release
        """
        before = get_success_data(
            api.get_party(base_full["lender_id"], base_full["lender_headers"]), 200
        )
        assert_fields_equal(
            before,
            {"committed_advance_cents": 0, "available_credit_cents": 50000000},
        )

        lien = get_success_data(
            api.perfect_lien(
                requested_lien, f.perfect_payload(), base_full["lender_headers"]
            ),
            200,
        )
        assert lien["advance_limit_cents"] == 290482

        lender = get_success_data(
            api.get_party(base_full["lender_id"], base_full["lender_headers"]), 200
        )
        assert_fields_equal(
            lender,
            {
                "committed_advance_cents": 290482,
                "available_credit_cents": 49709518,
            },
        )

    def test_revaluation_drags_the_committed_exposure_up_with_the_new_mark(
        self, api, base_full, requested_lien
    ):
        """
        Re-marking the same 949 bushels at 500 cents lifts eligible value to
        474500, the 25-basis-point fee to 1186, the warehouseman lien to 12194
        and net collateral to 462306, so the 70-percent limit becomes 323614 and
        the lender's committed exposure follows it, leaving 49676386 available.

        PRD: "On a lien that is already `PERFECTED`, it also adjusts the lender's
        `committed_advance_cents` by the difference between the new and the old
        advance limit, so the lender's committed exposure tracks the mark."

        Design: Difficulty/compensating_invariant/lender_credit_line_conserved_across_lien_perfect_and_release
        """
        get_success_data(
            api.perfect_lien(
                requested_lien, f.perfect_payload(), base_full["lender_headers"]
            ),
            200,
        )

        lien = get_success_data(
            api.revalue_lien(
                requested_lien, f.revalue_payload(500), base_full["lender_headers"]
            ),
            200,
        )
        assert_fields_equal(
            lien,
            {
                "eligible_value_cents": 474500,
                "admin_fee_cents": 1186,
                "warehouseman_lien_cents": 12194,
                "net_collateral_cents": 462306,
                "advance_limit_cents": 323614,
            },
        )

        lender = get_success_data(
            api.get_party(base_full["lender_id"], base_full["lender_headers"]), 200
        )
        assert_fields_equal(
            lender,
            {
                "committed_advance_cents": 323614,
                "available_credit_cents": 49676386,
            },
        )

    def test_release_unwinds_the_revalued_commitment_leaving_zero_drift(
        self, api, base_full, requested_lien
    ):
        """
        Release lowers the committed amount by what is currently committed —
        323614 after the re-mark, not the 290482 originally charged — so the line
        lands back on exactly 50000000, and possession returns to the depositor
        who pledged the receipt.

        PRD: "From `PERFECTED`, release requires the lien to be `PERFECTED` and
        the caller to be its lender; it sets `released_at` and
        `payoff_received_cents`, moves `lien_state` to `RELEASED`, drives the
        receipt's `encumbrance_state` from `PLEDGED` to `RELEASED`, restores
        `holder_party_id` to the captured `pledgor_party_id`, clears
        `registry_control_party_id`, and lowers the lender's
        `committed_advance_cents` by the amount **currently** committed for this
        lien — including any revaluation delta applied in the meantime — so that
        the lender's `available_credit_cents` returns exactly to its
        pre-perfection value."

        Design: Difficulty/compensating_invariant/lender_credit_line_conserved_across_lien_perfect_and_release
        """
        get_success_data(
            api.perfect_lien(
                requested_lien, f.perfect_payload(), base_full["lender_headers"]
            ),
            200,
        )
        get_success_data(
            api.revalue_lien(
                requested_lien, f.revalue_payload(500), base_full["lender_headers"]
            ),
            200,
        )

        lien = get_success_data(
            api.release_lien(
                requested_lien, f.release_payload(250000), base_full["lender_headers"]
            ),
            200,
        )
        assert_fields_equal(
            lien, {"lien_state": "RELEASED", "payoff_received_cents": 250000}
        )

        lender = get_success_data(
            api.get_party(base_full["lender_id"], base_full["lender_headers"]), 200
        )
        assert_fields_equal(
            lender,
            {"committed_advance_cents": 0, "available_credit_cents": 50000000},
        )

        receipt = get_success_data(
            api.get_receipt(base_full["receipt_id"], base_full["operator_headers"]), 200
        )
        assert_fields_equal(
            receipt,
            {
                "encumbrance_state": "RELEASED",
                "holder_party_id": base_full["depositor_id"],
                "registry_control_party_id": None,
            },
        )
