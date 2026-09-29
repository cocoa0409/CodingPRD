"""Two charge formulas whose composition order is normative.

The per-document examination fee rounds each document before summing, and the issuance
commission tier is selected from the gross exposure alone. Both rules are easy to compose
in the wrong order and both wrong orders produce a plausible-looking number.
"""

from test_helpers import (
    assert_facility_ledger,
    assert_issuance_charges,
    complying_presentation,
    issued_credit,
    lodge_claim,
    set_clock,
    settle_claim,
    setup_parties,
)

INVOICE_AMOUNTS = (3001000, 5001000)
DRAWN = 8002000


class TestDocumentExaminationFeeRoundsPerDocument:
    """Three documents whose exact fees each end on a half cent."""

    def _complying_file(self):
        parties = setup_parties(facility={"limit_cents": 50000000})
        ctx = issued_credit(
            parties,
            amount_cents=10000000,
            available_by="SIGHT_PAYMENT",
            tenor_days=0,
            latest_shipment_date="2026-10-31",
            expiry_date="2026-11-30",
            presentation_period_days=21,
        )
        set_clock("2026-09-14T09:00:00Z")
        return complying_presentation(ctx, INVOICE_AMOUNTS)

    def test_each_document_fee_is_rounded_before_it_joins_the_running_total(self, clock):
        """Rounding per document gives 7502; rounding the exact sum once gives 7501.

        PRD 3.9: "Step two is the per-document examination fee, and its rounding order is
        pinned: walk the presentation's PresentedDocument rows in `created_at` ascending
        order, and for each one round its own fee to whole cents **before** adding it to
        the running total."

        Design: Difficulty/combinatorial_formula/doc_examination_fee_round_per_document_then_sum
        """
        pctx = self._complying_file()
        assert pctx.presentation["document_count"] == 3

        settled = settle_claim(lodge_claim(pctx, "PAYMENT", DRAWN)["id"])

        assert settled["doc_examination_fee_cents"] == 7502
        assert settled["doc_examination_fee_cents"] != 7501

    def test_every_document_contributes_and_the_net_follows_the_fee(self, clock):
        """A bill of lading contributes its flat fee alongside the two invoice fees.

        PRD 3.9: "A `COMMERCIAL_INVOICE` contributes its `invoice_amount_cents` multiplied
        by 5 basis points, divided by 10,000 and rounded half up; every other document
        type contributes a flat 3,500 cents."

        Design: Difficulty/combinatorial_formula/doc_examination_fee_round_per_document_then_sum
        """
        pctx = self._complying_file()

        settled = settle_claim(lodge_claim(pctx, "PAYMENT", DRAWN)["id"])

        assert settled["commission_cents"] == 9602
        assert settled["doc_examination_fee_cents"] == 7502
        assert settled["net_proceeds_cents"] == 7984896
        assert pctx.refresh()["settlement_status"] == "PAID"


class TestCommissionTierKeyedOnGrossExposure:
    """A credit whose gross sits in the middle tier and whose chargeable total does not."""

    def _issued(self):
        parties = setup_parties(facility={"limit_cents": 60000000})
        return issued_credit(
            parties,
            amount_cents=49990000,
            available_by="SIGHT_PAYMENT",
            tenor_days=0,
            tolerance_pct=0,
            latest_shipment_date="2026-09-15",
            expiry_date="2026-10-05",
            presentation_period_days=21,
        )

    def test_tier_is_read_from_gross_exposure_and_not_from_the_charged_total(self, clock):
        """Gross 49,990,000 selects 10 bps even though the charged total passes 50,000,000.

        PRD 3.3: "The tier is emphatically **not** selected from
        `committed_allocation_cents`, not from `chargeable_utilisation_cents`, and not
        from any figure that already contains a charge."

        Design: Difficulty/combinatorial_formula/commission_tier_keyed_on_gross_not_chargeable_total
        """
        ctx = self._issued()

        assert_issuance_charges(
            ctx.credit,
            gross_exposure_cents=49990000,
            commission_bps_applied=10,
            base_commission_cents=49990,
            total_charge_cents=49990,
            chargeable_utilisation_cents=50039990,
        )
        assert ctx.credit["commission_bps_applied"] != 7
        assert ctx.credit["base_commission_cents"] != 35028
        assert ctx.credit["chargeable_utilisation_cents"] > 50000000

    def test_the_charged_total_lands_on_the_facility_and_the_deadline_is_the_expiry(self, clock):
        """The facility absorbs the charged total; the deadline is the earlier of the pair.

        PRD 3.3: "The `presentation_deadline_date` is re-derived as the earlier of
        `expiry_date` and `latest_shipment_date` advanced by `presentation_period_days`
        days, inclusive."

        Design: Difficulty/combinatorial_formula/commission_tier_keyed_on_gross_not_chargeable_total
        """
        ctx = self._issued()

        assert ctx.credit["presentation_deadline_date"] == "2026-10-05"
        assert_facility_ledger(
            ctx.refresh_facility(),
            allocated_cents=50039990,
            available_cents=9960010,
            restrict_threshold_cents=57000000,
            utilisation_posture="OPEN",
        )
