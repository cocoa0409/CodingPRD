"""Immediate consistency: the write response already carries the end of its own cascade.

Nothing in this service is eventually consistent. The response to a write must already hold
every figure the cascade computed, and a plain read taken straight afterwards — with no sweep,
no refresh and no second write in between — must agree with it. Both directions are exercised:
the issuance cascade that commits exposure, and the refusal cascade that gives it back.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    api_client,
    approved_credit,
    assert_chargeable_sum,
    assert_credit_drawing_ledger,
    assert_facility_ledger,
    assert_fields_equal,
    assert_issuance_charges,
    conclude_examination,
    credit_officer_headers,
    issue_credit,
    issued_credit,
    list_credit_allocation_rows,
    list_discrepancy_rows,
    raise_discrepancy,
    refuse_presentation,
    setup_parties,
    submitted_presentation,
)

THE_CLOCK_INSTANT = "2026-08-10T09:00:00.000Z"
THE_CLOCK_DATE = "2026-08-10"

_APPLICANT = {"legal_name": "Baltic Timber Imports AS", "country_code": "NO"}
_BANK = {
    "bank_name": "Nordkyst Bank",
    "swift_bic": "NDKBNOKK",
    "country_code": "NO",
    "country_risk_score": 12,
    "credit_rating": "AA",
    "confirmation_appetite_cents": 90000000,
}
_BENEFICIARY = {"beneficiary_name": "Riga Sawmill SIA", "country_code": "LV"}


def _parties():
    """The standard four counterparties: a NO applicant, a NO bank and an LV beneficiary."""
    return setup_parties(
        applicant=dict(_APPLICANT),
        facility={"limit_cents": 50000000, "collateral_required_pct": 0},
        bank=dict(_BANK),
        beneficiary=dict(_BENEFICIARY),
    )


class TestTheIssuanceResponseAlreadyCarriesEveryDerivedField:
    """A 10,000,000 sight credit on a 50,000,000 facility, priced over two chargeable quarters.

    An implementation that computed the ledger lazily would answer this request with zeros and
    only later produce the right numbers, so every figure is read out of the issuance response
    itself before anything else touches the service.
    """

    def test_the_issue_response_holds_the_exposure_the_pricing_and_both_windows(self, clock):
        """One response, every derived field: exposure, commission, deadline and window.

        PRD 3.3: "Second, the commission tier is selected from `gross_exposure_cents` **alone**
        and is recorded in `commission_bps_applied`: 15 basis points when `gross_exposure_cents`
        is at most 5,000,000 cents, 10 basis points when it is above that but at most 50,000,000
        cents, and 7 basis points above that."
        PRD 3.3: "Third, `base_commission_cents` is the larger of a 25,000-cent floor and the
        result of multiplying `gross_exposure_cents` by `commission_bps_applied` and by the
        quarter count, dividing by 10,000 and rounding half up."
        PRD 3.3: "Fifth and last, `total_charge_cents` is `base_commission_cents` plus
        `confirmation_charge_cents`, and `chargeable_utilisation_cents` is
        `committed_allocation_cents` plus `total_charge_cents`."
        PRD 3.3: "The `presentation_deadline_date` is re-derived as the earlier of `expiry_date`
        and `latest_shipment_date` advanced by `presentation_period_days` days, inclusive."

        Design: Corner/consistency_model/immediate_visibility_issuance_response_already_carries_every_derived_field
        """
        ctx = approved_credit(_parties())
        assert ctx.credit["provisional_allocation_cents"] == 10000000, (
            "the draft already carried the provisional figure, tolerance and tenor forced to zero"
        )

        issued = issue_credit(ctx.credit_id)

        assert_fields_equal(issued, status="ISSUED", issue_date=THE_CLOCK_DATE)
        assert_issuance_charges(
            issued,
            max_drawable_cents=10000000,
            gross_exposure_cents=10000000,
            committed_allocation_cents=10000000,
            commission_bps_applied=10,
            base_commission_cents=25000,
            confirmation_charge_cents=0,
            total_charge_cents=25000,
            chargeable_utilisation_cents=10025000,
        )
        assert_chargeable_sum(issued)
        assert_credit_drawing_ledger(
            issued, drawn_settled_cents=0, reserved_cents=0, available_cents=10000000
        )
        assert_fields_equal(
            issued,
            presentation_deadline_date="2026-11-21",
            confirmation_window_start="2026-08-10",
            confirmation_window_end="2026-12-21",
        )

    def test_the_facility_and_the_allocation_row_agree_with_that_response_at_once(self, clock):
        """No sweep and no second write stand between the issuance and these two plain reads.

        PRD 3.3: "**Hop one** creates a facility allocation row: its `facility_id` and
        `credit_id` name the facility and the credit, its `basis` is `COMMITTED_ISSUANCE`, its
        `status` is `OPEN`, its `allocated_cents` is the credit's `committed_allocation_cents`
        and its `charge_cents` is the credit's `total_charge_cents`; its `released_cents` starts
        at 0 and its `released_at` is unset."
        PRD 3.3: "**Hop two** is caused by hop one: the new open row re-drives the facility's
        exposure ledger, so the facility's `allocated_cents` rises by exactly the credit's
        `chargeable_utilisation_cents`, its `available_cents` falls by the same amount, and its
        `version` increments by one."

        Design: Corner/consistency_model/immediate_visibility_issuance_response_already_carries_every_derived_field
        """
        ctx = approved_credit(_parties())
        issued = issue_credit(ctx.credit_id)

        facility = validate_success(
            api_client.get_facility(ctx.parties.facility_id, credit_officer_headers())
        )
        assert_facility_ledger(
            facility,
            allocated_cents=10025000,
            available_cents=39975000,
            restrict_threshold_cents=47500000,
            utilisation_posture="OPEN",
            status="ACTIVE",
            suspended_reason=None,
        )
        assert facility["allocated_cents"] == issued["chargeable_utilisation_cents"]

        rows = list_credit_allocation_rows(ctx.credit_id)
        assert len(rows) == 1
        assert_fields_equal(
            rows[0],
            facility_id=ctx.parties.facility_id,
            credit_id=ctx.credit_id,
            basis="COMMITTED_ISSUANCE",
            status="OPEN",
            allocated_cents=issued["committed_allocation_cents"],
            charge_cents=issued["total_charge_cents"],
            released_cents=0,
            released_at=None,
        )
        assert rows[0]["allocated_cents"] + rows[0]["charge_cents"] == facility["allocated_cents"]


class TestTheRefusalResponseAlreadyReflectsTheReleasedReservation:
    """The refusal notice runs a three-hop compensating cascade in one request.

    An implementation that deferred the ledger recompute to the sweep would still show four
    million reserved here. The facility, by contrast, must not move at all: exposure was
    committed at issuance and the credit itself is still outstanding.
    """

    @staticmethod
    def _a_discrepant_file():
        ctx = issued_credit(_parties())
        assert_credit_drawing_ledger(ctx.credit, reserved_cents=0, available_cents=10000000)
        pctx = submitted_presentation(ctx, invoice_amounts=(4000000,))
        assert_credit_drawing_ledger(
            ctx.refresh(), reserved_cents=4000000, available_cents=6000000
        )
        raise_discrepancy(pctx, "GOODS_DESCRIPTION_MISMATCH")
        conclude_examination(pctx)
        assert pctx.refresh()["examination_status"] == "DISCREPANT"
        return ctx, pctx

    def test_the_refusal_response_is_already_terminal_and_already_void(self, clock):
        """`REFUSED`, `VOID`, the notice instant and the upheld defect all arrive together.

        PRD 3.7: "Refusal moves `examination_status` `DISCREPANT → REFUSED`, which is terminal,
        sets `refusal_notice_sent_at` to the clock instant, records the `disposal_instruction`,
        and moves every remaining `IDENTIFIED` Discrepancy to `UPHELD`."
        PRD 3.7: "Hop one moves `settlement_status` `UNSETTLED → VOID`."

        Design: Corner/consistency_model/immediate_visibility_refusal_response_already_reflects_the_released_reservation
        """
        _, pctx = self._a_discrepant_file()

        refusal = refuse_presentation(pctx)

        assert_fields_equal(
            refusal,
            examination_status="REFUSED",
            settlement_status="VOID",
            refusal_notice_sent_at=THE_CLOCK_INSTANT,
            disposal_instruction="RETURN_TO_PRESENTER",
        )
        assert [row["status"] for row in list_discrepancy_rows(pctx.presentation_id)] == ["UPHELD"]

    def test_the_next_read_shows_the_credit_restored_and_the_facility_untouched(self, clock):
        """Hops two and three are visible in the very next read, and the facility is not.

        PRD 3.7: "Hop two follows from hop one: a void presentation leaves the drawable ledger's
        live set, so the credit's `reserved_cents` falls by exactly this presentation's
        `drawn_amount_cents`."
        PRD 3.7: "Hop three follows from hop two: `available_cents` is re-derived as
        `max_drawable_cents` minus `reserved_cents` minus `drawn_settled_cents`, restoring
        precisely the value the credit had before the submission, and the credit's `version`
        increments."
        PRD 3.7: "The facility is deliberately untouched: `allocated_cents` does not move,
        because facility exposure is committed at issuance and not at drawing, and the credit
        itself remains outstanding."

        Design: Corner/consistency_model/immediate_visibility_refusal_response_already_reflects_the_released_reservation
        """
        ctx, pctx = self._a_discrepant_file()

        refuse_presentation(pctx)

        credit = ctx.refresh()
        assert_credit_drawing_ledger(
            credit,
            drawn_settled_cents=0,
            reserved_cents=0,
            available_cents=10000000,
            max_drawable_cents=10000000,
        )
        assert credit["status"] == "ISSUED", "refusing a presentation does not touch the credit"
        assert_facility_ledger(
            ctx.parties.refresh_facility(),
            allocated_cents=10025000,
            available_cents=39975000,
            status="ACTIVE",
        )
