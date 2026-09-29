"""Two boundaries probed one unit either side of the line.

A facility with exactly the required headroom admits an issuance while a facility one cent
short refuses it, and a refusal stamped on the final millisecond of the examination period
is timely while one stamped a millisecond later is preclusion-barred. Both metrics are
integers — cents and milliseconds — so there is no rounding slack to hide behind.
"""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import (
    api_client,
    approved_credit,
    assert_end_of_day_instant,
    assert_facility_ledger,
    create_facility,
    credit_officer_headers,
    discrepant_presentation,
    document_examiner_headers,
    draft_credit,
    factories,
    issue_credit,
    issued_credit,
    refuse_presentation,
    set_clock,
    setup_parties,
    submit_credit_for_approval,
    approve_credit,
    trade_finance_officer_headers,
)

FIVE_MILLION_TERMS = {
    "amount_cents": 5000000,
    "available_by": "SIGHT_PAYMENT",
    "tenor_days": 0,
    "tolerance_pct": 0,
    "latest_shipment_date": "2026-09-15",
    "expiry_date": "2026-10-05",
    "presentation_period_days": 21,
}
CHARGEABLE = 5025000


def _read_facility(facility_id):
    return validate_success(api_client.get_facility(facility_id, credit_officer_headers()))


def _attempt_issue(credit_id):
    return api_client.issue_credit(
        credit_id, factories.issue_payload(), trade_finance_officer_headers()
    )


class TestFacilityHeadroomExactEqualityAdmitsIssuance:
    """Two facilities one cent apart, each carrying an identical 5,025,000 issuance."""

    def _exact_facility_credit(self):
        parties = setup_parties(facility={"limit_cents": CHARGEABLE})
        return approved_credit(parties, None, **FIVE_MILLION_TERMS)

    def _one_cent_short_credit(self):
        parties = setup_parties(facility={"limit_cents": CHARGEABLE})
        short = create_facility(parties.applicant_id, limit_cents=CHARGEABLE - 1)
        ctx = draft_credit(parties, None, facility_id=short["id"], **FIVE_MILLION_TERMS)
        submit_credit_for_approval(ctx.credit_id)
        approve_credit(ctx.credit_id)
        ctx.refresh()
        return ctx, short["id"]

    def test_an_issuance_consuming_the_headroom_to_the_cent_is_admitted(self, clock):
        """5,025,000 against 5,025,000 of headroom leaves zero and succeeds.

        PRD 2.11: "Capacity comparisons throughout this service admit exact equality: an
        allocation that consumes precisely the available headroom succeeds, a drawing that
        consumes precisely the drawable balance succeeds, and a confirming line whose peak
        occupancy exactly equals the bank's appetite is admitted."

        Design: Difficulty/boundary_precision_check/facility_headroom_exact_equality_admits_issuance
        """
        ctx = self._exact_facility_credit()

        response = _attempt_issue(ctx.credit_id)

        issued = validate_success(response, 200)
        assert issued["status"] == "ISSUED"
        assert issued["gross_exposure_cents"] == 5000000
        assert issued["commission_bps_applied"] == 15
        assert issued["base_commission_cents"] == 25000
        assert issued["chargeable_utilisation_cents"] == CHARGEABLE

    def test_the_admitted_issuance_empties_the_facility_and_trips_the_threshold(self, clock):
        """Zero headroom left is still a legal ledger, and it is past the restriction line.

        PRD 3.3: "The committed allocation plus the issuance charges must fit inside the
        facility's `available_cents`, with exact equality admitted, else
        `ERR_FACILITY_LIMIT_EXCEEDED` (422)."

        Design: Difficulty/boundary_precision_check/facility_headroom_exact_equality_admits_issuance
        """
        ctx = self._exact_facility_credit()

        issue_credit(ctx.credit_id)

        assert_facility_ledger(
            ctx.refresh_facility(),
            allocated_cents=CHARGEABLE,
            available_cents=0,
            restrict_threshold_cents=4773750,
            utilisation_posture="RESTRICTED",
            status="SUSPENDED",
            suspended_reason="RESTRICT_THRESHOLD_BREACH",
        )

    def test_one_cent_less_headroom_refuses_the_same_issuance(self, clock):
        """5,025,000 against 5,024,999 fails, so the comparison is strict and not lenient.

        PRD 3.3: "The committed allocation plus the issuance charges must fit inside the
        facility's `available_cents`, with exact equality admitted, else
        `ERR_FACILITY_LIMIT_EXCEEDED` (422)."

        Design: Difficulty/boundary_precision_check/facility_headroom_exact_equality_admits_issuance
        """
        ctx, short_facility_id = self._one_cent_short_credit()

        validate_error(_attempt_issue(ctx.credit_id), "ERR_FACILITY_LIMIT_EXCEEDED", 422)

        assert ctx.refresh()["status"] == "APPROVED"
        assert ctx.credit["committed_allocation_cents"] == 0
        assert_facility_ledger(
            _read_facility(short_facility_id),
            allocated_cents=0,
            available_cents=CHARGEABLE - 1,
            restrict_threshold_cents=4773749,
            utilisation_posture="OPEN",
            status="ACTIVE",
        )


class TestExaminationDeadlineFinalMillisecondAdmitsRefusal:
    """Two discrepant files presented the same Monday, refused a millisecond apart."""

    DEADLINE_DATE = "2026-09-21"
    LAST_INSTANT = "2026-09-21T23:59:59.999Z"
    FIRST_INSTANT_AFTER = "2026-09-22T00:00:00.000Z"

    def _two_discrepant_files(self):
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
        first = discrepant_presentation(
            ctx, "GOODS_DESCRIPTION_MISMATCH", "MATERIAL", (2000000,)
        )
        second = discrepant_presentation(
            ctx, "GOODS_DESCRIPTION_MISMATCH", "MATERIAL", (2000000,)
        )
        return ctx, first, second

    def test_five_banking_days_from_a_monday_skip_the_weekend(self, clock):
        """A Monday presentation is examinable until the following Monday's last millisecond.

        PRD 3.6: "The day of presentation itself is never counted, even when it is a
        banking day."

        Design: Difficulty/boundary_precision_check/examination_deadline_final_millisecond_admits_refusal
        """
        _ctx, first, second = self._two_discrepant_files()

        for pctx in (first, second):
            assert_end_of_day_instant(
                pctx.presentation["examination_deadline"],
                self.DEADLINE_DATE,
                "examination_deadline",
            )

    def test_a_refusal_on_the_final_millisecond_is_timely(self, clock):
        """The deadline instant is inside the period, so this refusal is admitted.

        PRD 2.11: "The **examination period** ends at `examination_deadline`, an instant,
        and that instant is **inside** the period: an action stamped at exactly
        `23:59:59.999Z` on the final banking day is timely, and one millisecond later is
        not."

        Design: Difficulty/boundary_precision_check/examination_deadline_final_millisecond_admits_refusal
        """
        _ctx, first, _second = self._two_discrepant_files()
        set_clock(self.LAST_INSTANT)

        refused = refuse_presentation(first, "RETURN_TO_PRESENTER")

        assert refused["examination_status"] == "REFUSED"
        assert refused["settlement_status"] == "VOID"
        assert refused["refusal_notice_sent_at"] == self.LAST_INSTANT
        assert refused["disposal_instruction"] == "RETURN_TO_PRESENTER"

    def test_a_refusal_one_millisecond_later_is_preclusion_barred(self, clock):
        """One millisecond past the deadline the bank is barred and must honour.

        PRD 3.7: "The presentation must be `DISCREPANT` with `discrepancy_count` of at
        least one, and the clock instant must be at or before `examination_deadline`, else
        `ERR_EXAMINATION_PERIOD_EXPIRED` (409) — past that instant the bank is
        preclusion-barred and must honour, whatever the documents look like."

        Design: Difficulty/boundary_precision_check/examination_deadline_final_millisecond_admits_refusal
        """
        ctx, first, second = self._two_discrepant_files()
        set_clock(self.LAST_INSTANT)
        refuse_presentation(first, "RETURN_TO_PRESENTER")
        set_clock(self.FIRST_INSTANT_AFTER)

        response = api_client.refuse_presentation(
            second.presentation_id,
            factories.refusal_payload("RETURN_TO_PRESENTER"),
            document_examiner_headers(),
        )

        validate_error(response, "ERR_EXAMINATION_PERIOD_EXPIRED", 409)
        still_open = second.refresh()
        assert still_open["examination_status"] == "DISCREPANT"
        assert still_open["settlement_status"] == "UNSETTLED"
        assert still_open["refusal_notice_sent_at"] is None
        credit = ctx.refresh()
        assert credit["reserved_cents"] == 2000000
        assert credit["available_cents"] == 8000000
