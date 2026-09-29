"""Two cascades where each hop is caused by the hop above it.

Issuing one large credit debits the facility, the debit crosses the restriction threshold,
the breach suspends the facility, and the suspension holds every approved sibling. Refusing
a presentation voids its settlement dimension, the void drops it out of the live set, and
that restores the credit's drawable balance. Neither chain is triggered directly.
"""

from test_helpers import (
    approved_credit,
    assert_facility_ledger,
    assert_instant_with_milliseconds,
    discrepant_presentation,
    issue_credit,
    issued_credit,
    list_credit_allocation_rows,
    list_discrepancy_rows,
    refuse_presentation,
    set_clock,
    setup_parties,
)


class TestIssueCreditSuspendsFacilityAndHoldsSiblings:
    """A 95,000,000 issuance lands exactly on a 95,000,000 restriction threshold."""

    def _three_approved(self):
        parties = setup_parties(facility={"limit_cents": 100000000})
        terms = {
            "available_by": "SIGHT_PAYMENT",
            "tenor_days": 0,
            "tolerance_pct": 0,
            "latest_shipment_date": "2026-09-15",
            "expiry_date": "2026-10-05",
            "presentation_period_days": 21,
        }
        first = approved_credit(parties, None, amount_cents=95000000, **terms)
        second = approved_credit(parties, None, amount_cents=1000000, **terms)
        third = approved_credit(parties, None, amount_cents=2000000, **terms)
        return parties, first, second, third

    def test_hop_one_opens_a_committed_allocation_row_carrying_the_charges(self, clock):
        """The first hop writes an allocation row, not a patch on the facility.

        PRD 3.3: "**Hop one** creates a facility allocation row: its `facility_id` and
        `credit_id` name the facility and the credit, its `basis` is `COMMITTED_ISSUANCE`,
        its `status` is `OPEN`, its `allocated_cents` is the credit's
        `committed_allocation_cents` and its `charge_cents` is the credit's
        `total_charge_cents`; its `released_cents` starts at 0 and its `released_at` is
        unset."

        Design: Difficulty/transitive_cascade/issue_credit_depth4_facility_suspension_holds_sibling_credits
        """
        _parties, first, _second, _third = self._three_approved()

        issued = issue_credit(first.credit_id)

        assert issued["status"] == "ISSUED"
        assert issued["gross_exposure_cents"] == 95000000
        assert issued["commission_bps_applied"] == 7
        assert issued["base_commission_cents"] == 66500
        assert issued["chargeable_utilisation_cents"] == 95066500

        rows = list_credit_allocation_rows(first.credit_id)
        assert len(rows) == 1
        row = rows[0]
        assert row["basis"] == "COMMITTED_ISSUANCE"
        assert row["status"] == "OPEN"
        assert row["allocated_cents"] == 95000000
        assert row["charge_cents"] == 66500
        assert row["released_cents"] == 0
        assert row["released_at"] is None

    def test_hops_two_and_three_debit_the_facility_and_trip_its_threshold(self, clock):
        """The new open row re-drives the ledger, and the ledger trips the breach.

        PRD 3.3: "**Hop three** is caused by hop two: if the facility's new
        `allocated_cents` has reached or passed `restrict_threshold_cents`,
        `utilisation_posture` flips `OPEN → RESTRICTED` and the facility's `status` flips
        `ACTIVE → SUSPENDED` with `suspended_reason` set to `RESTRICT_THRESHOLD_BREACH`."

        Design: Difficulty/transitive_cascade/issue_credit_depth4_facility_suspension_holds_sibling_credits
        """
        parties, first, _second, _third = self._three_approved()

        issue_credit(first.credit_id)

        assert_facility_ledger(
            parties.refresh_facility(),
            allocated_cents=95066500,
            available_cents=4933500,
            restrict_threshold_cents=95000000,
            utilisation_posture="RESTRICTED",
            status="SUSPENDED",
            suspended_reason="RESTRICT_THRESHOLD_BREACH",
        )

    def test_hop_four_holds_every_approved_sibling_on_the_same_facility(self, clock):
        """The suspension, not the request, is what moves the two untouched siblings.

        PRD 3.3: "**Hop four** is caused by hop three: the suspension itself moves every
        sibling credit on the same facility whose status is `APPROVED` — this credit
        excluded, since it is now `ISSUED` — to `ON_HOLD`, processed in `created_at`
        ascending order, each sibling's `version` incrementing by one."

        Design: Difficulty/transitive_cascade/issue_credit_depth4_facility_suspension_holds_sibling_credits
        """
        _parties, first, second, third = self._three_approved()
        assert second.refresh()["status"] == "APPROVED"
        assert third.refresh()["status"] == "APPROVED"

        issue_credit(first.credit_id)

        assert first.refresh()["status"] == "ISSUED"
        assert second.refresh()["status"] == "ON_HOLD"
        assert third.refresh()["status"] == "ON_HOLD"


class TestRefusalReleasesReservationAndRestoresAvailable:
    """A refused presentation walks its drawing back out of the credit's ledger."""

    def _discrepant_file(self):
        ctx = issued_credit(
            setup_parties(facility={"limit_cents": 50000000}),
            amount_cents=10000000,
            available_by="SIGHT_PAYMENT",
            tenor_days=0,
            tolerance_pct=0,
            latest_shipment_date="2026-10-31",
            expiry_date="2026-11-30",
            presentation_period_days=21,
        )
        set_clock("2026-09-14T09:00:00Z")
        return discrepant_presentation(
            ctx, "GOODS_DESCRIPTION_MISMATCH", "MATERIAL", (4000000,)
        )

    def test_submission_reserves_the_drawing_before_the_refusal(self, clock):
        """The compensating chain has something to undo only because submission reserved.

        PRD 3.6: "The credit's `reserved_cents` is the sum of `drawn_amount_cents` over the
        live set, `drawn_settled_cents` is the sum over the settled set, and
        `available_cents` is `max_drawable_cents` minus `reserved_cents` minus
        `drawn_settled_cents`."

        Design: Difficulty/transitive_cascade/refuse_presentation_releases_reservation_and_restores_available
        """
        pctx = self._discrepant_file()

        credit = pctx.refresh_credit()
        assert credit["reserved_cents"] == 4000000
        assert credit["available_cents"] == 6000000

    def test_the_refusal_notice_voids_the_settlement_dimension(self, clock):
        """Hop zero refuses, and hop one takes the settlement dimension to `VOID`.

        PRD 3.7: "Refusal moves `examination_status` `DISCREPANT → REFUSED`, which is
        terminal, sets `refusal_notice_sent_at` to the clock instant, records the
        `disposal_instruction`, and moves every remaining `IDENTIFIED` Discrepancy to
        `UPHELD`."

        Design: Difficulty/transitive_cascade/refuse_presentation_releases_reservation_and_restores_available
        """
        pctx = self._discrepant_file()

        refused = refuse_presentation(pctx, "HOLD_AT_DISPOSAL")

        assert refused["examination_status"] == "REFUSED"
        assert refused["disposal_instruction"] == "HOLD_AT_DISPOSAL"
        assert_instant_with_milliseconds(
            refused["refusal_notice_sent_at"], "refusal_notice_sent_at"
        )
        assert refused["refusal_notice_sent_at"] == "2026-09-14T09:00:00.000Z"
        assert refused["settlement_status"] == "VOID"
        codes = list_discrepancy_rows(pctx.presentation_id)
        assert [row["status"] for row in codes] == ["UPHELD"]

    def test_the_void_restores_the_credit_and_leaves_the_facility_alone(self, clock):
        """Hops two and three restore `available_cents`; the facility is untouched.

        PRD 3.7: "The facility is deliberately untouched: `allocated_cents` does not move,
        because facility exposure is committed at issuance and not at drawing, and the
        credit itself remains outstanding."

        Design: Difficulty/transitive_cascade/refuse_presentation_releases_reservation_and_restores_available
        """
        pctx = self._discrepant_file()

        refuse_presentation(pctx, "HOLD_AT_DISPOSAL")

        credit = pctx.refresh_credit()
        assert credit["reserved_cents"] == 0
        assert credit["available_cents"] == 10000000
        assert credit["drawn_settled_cents"] == 0
        assert credit["status"] == "ISSUED"
        assert_facility_ledger(
            pctx.parties.refresh_facility(),
            allocated_cents=10025000,
            available_cents=39975000,
        )
