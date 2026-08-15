"""Close-time trustee compensation branches and the sale void/retry cycle."""
from test_helpers import (
    AUCT,
    CM,
    get_case,
    list_case_disbursements,
    schedule_sale,
    setup_closed_sale,
    trustee_fee_disbursement,
    validate_success,
)


class TestTrusteeCompensationBranches:
    def test_third_party_win_fees_on_winning_bid(self, api):
        """PRD §3.8: "The trustee's compensation is computed at close. The fee base is the `winning_bid_cents` when a third party wins and the `total_debt_at_close_cents` when the beneficiary wins; the fee itself is one-half of one percent of the base rounded half-up to whole cents, bounded below by seven hundred fifty dollars (75000 cents) and above by four thousand seven hundred fifty dollars (475000 cents)."

        Design: Difficulty/combinatorial_formula/trustee_fee_winner_type_min_max_branch
        """
        ctx = setup_closed_sale(
            "BEN-F1A", venue_name="VEN-F1A", loan_reference="LN-F1A",
            opening_bid_cents=42_000_000, max_bid_cents=43_000_000,
            strategy="UP_TO_MAX", bid_amount_cents=43_000_000,
            bidder_name="Bidder A", bidder_email="ba@bid.example",
        )
        sale = ctx["sale"]
        assert sale["winner_type"] == "THIRD_PARTY"
        assert sale["winning_bid_cents"] == 43_000_000
        fee = trustee_fee_disbursement(ctx["case"]["id"])
        # min(475000, max(75000, round(0.005 * 43000000))) == 215000
        assert fee["amount_cents"] == 215_000, (
            f"third-party base is the winning bid; got {fee['amount_cents']}"
        )
        assert fee["status"] == "CLEARED"

    def test_beneficiary_win_fees_on_total_debt_at_close(self, api):
        """PRD §3.8: "The trustee's compensation is computed at close. The fee base is the `winning_bid_cents` when a third party wins and the `total_debt_at_close_cents` when the beneficiary wins; the fee itself is one-half of one percent of the base rounded half-up to whole cents, bounded below by seven hundred fifty dollars (75000 cents) and above by four thousand seven hundred fifty dollars (475000 cents). The `total_debt_at_close_cents` is the case's `unpaid_principal_balance_cents` plus per-diem interest on that principal accruing from the `last_interest_paid_date` through the close date, computed under the per-diem rule of Section 3.6."
        PRD §3.8: "When no qualifying bid exists, the beneficiary takes the property: `winner_type` becomes `BENEFICIARY` and `winning_bid_cents` becomes the sale's `opening_bid_cents` — the credit bid — with `winning_bidder_registration_id` left null."

        Design: Difficulty/combinatorial_formula/trustee_fee_winner_type_min_max_branch
        """
        ctx = setup_closed_sale(
            "BEN-F1B", venue_name="VEN-F1B", loan_reference="LN-F1B",
            opening_bid_cents=42_000_000, max_bid_cents=43_000_000,
            strategy="UP_TO_MAX", bid_amount_cents=None,
        )
        sale = ctx["sale"]
        assert sale["winner_type"] == "BENEFICIARY"
        assert sale["winning_bid_cents"] == 42_000_000
        assert sale["winning_bidder_registration_id"] is None
        # 7890 per-diem x 145 days (2026-07-01 -> 2026-11-23) == 1144050 interest.
        assert sale["total_debt_at_close_cents"] == 41_144_050
        fee = trustee_fee_disbursement(ctx["case"]["id"])
        # min(475000, max(75000, round(0.005 * 41144050))) == 205720; the
        # 42000000 opening bid would wrongly yield 210000.
        assert fee["amount_cents"] == 205_720, (
            f"beneficiary-win base is total debt at close; got {fee['amount_cents']}"
        )


class TestSaleVoidRetryCycle:
    def _closed_third_party_sale(self, api):
        return setup_closed_sale(
            "BEN-C1", venue_name="VEN-C1", loan_reference="LN-C1",
            opening_bid_cents=42_000_000, max_bid_cents=43_000_000,
            strategy="UP_TO_MAX", bid_amount_cents=43_000_000,
            bidder_name="Bidder C", bidder_email="bc@bid.example",
        )

    def test_void_rewinds_case_notice_sale_and_registration(self, api):
        """PRD §3.8: "The void is a full compensation unwind. The sale becomes `VOIDED`; a trustee's deed still in `DRAFTED` status for the sale becomes `VOIDED`; the winner's `DEPOSIT_APPLIED` registration returns to `REFUND_PENDING`; every `CLEARED` proceeds-application disbursement created by this sale's close — the `TRUSTEE_FEE`, each `BENEFICIARY_COST_REIMBURSEMENT`, and the `BENEFICIARY_DEBT_PAYOFF` — becomes `REVERSED`; every cost advance that close had set to `REIMBURSED` returns to `APPROVED`, restoring the beneficiary's outstanding-advances total; the case's `undistributed_surplus_cents` returns to zero; the parent notice of trustee's sale falls back from `SALE_SCHEDULED` to `PUBLICATION_COMPLETE` — the publications remain valid, making the notice immediately re-schedulable; and the case moves from `SOLD` back to `NOTS_RECORDED`, its `version` incrementing."

        Design: Difficulty/non_linear_state_machine/case_sale_retry_cycle_via_void
        """
        ctx = self._closed_third_party_sale(api)
        sale_id = ctx["sale"]["id"]
        voided = validate_success(
            api.void_sale(sale_id, {"reason": "defective sale conduct discovered"},
                          AUCT),
            200,
        )
        assert voided["status"] == "VOIDED"
        case = get_case(ctx["case"]["id"])
        assert case["lifecycle_status"] == "NOTS_RECORDED", (
            f"cycle re-entry, got {case['lifecycle_status']}"
        )
        assert case["undistributed_surplus_cents"] == 0
        nots = validate_success(api.get_nots(ctx["nots"]["id"], CM), 200)
        assert nots["status"] == "PUBLICATION_COMPLETE", (
            "publications survive the void; the notice is immediately re-schedulable"
        )
        reg = validate_success(
            api.get_bidder_registration(ctx["registration"]["id"], AUCT), 200
        )
        assert reg["status"] == "REFUND_PENDING", (
            f"the winner's DEPOSIT_APPLIED registration returns, got {reg['status']}"
        )

    def test_void_reverses_disbursements_and_allows_reschedule(self, api):
        """PRD §3.8: "every `CLEARED` proceeds-application disbursement created by this sale's close — the `TRUSTEE_FEE`, each `BENEFICIARY_COST_REIMBURSEMENT`, and the `BENEFICIARY_DEBT_PAYOFF` — becomes `REVERSED`"
        PRD §3.8: "This backward edge is the sale-retry cycle: a case may pass from `NOTS_RECORDED` through `SALE_SCHEDULED` and `SOLD` and back to `NOTS_RECORDED` more than once before the deed finally records."

        Design: Difficulty/non_linear_state_machine/case_sale_retry_cycle_via_void
        """
        ctx = self._closed_third_party_sale(api)
        case_id = ctx["case"]["id"]
        sale_id = ctx["sale"]["id"]
        cleared = list_case_disbursements(case_id)
        assert cleared, "close must have created proceeds-application disbursements"
        validate_success(
            api.void_sale(sale_id, {"reason": "defective sale conduct discovered"},
                          AUCT),
            200,
        )
        reversed_rows = list_case_disbursements(case_id)
        assert len(reversed_rows) == len(cleared)
        assert all(d["status"] == "REVERSED" for d in reversed_rows), (
            f"every proceeds-application disbursement is compensated: {reversed_rows}"
        )

        sale2 = schedule_sale(ctx["nots"]["id"], venue_name="VEN-C1",
                              scheduled_sale_start_at="2026-12-07T10:00:00Z")
        assert sale2["id"] != sale_id
        assert sale2["status"] == "SCHEDULED"
        case = get_case(case_id)
        assert case["lifecycle_status"] == "SALE_SCHEDULED"
        nots = validate_success(api.get_nots(ctx["nots"]["id"], CM), 200)
        assert nots["status"] == "SALE_SCHEDULED"
