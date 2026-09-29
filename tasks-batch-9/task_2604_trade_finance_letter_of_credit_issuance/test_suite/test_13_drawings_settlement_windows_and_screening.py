"""Drawings, settlement waterfalls, window conventions and sanctions scoring.

The drawable ledger's input set on both of its exclusions, the five-banking-day examination
walk across a weekend, the half-cent rounding tie in the proceeds waterfall, the acceptance
variant that reserves rather than draws, the negotiation waterfall and the claim whose fees
swamp it, the presentation and confirmation windows with their opposite bounds, the
confirming-bank selector's filter-then-score order, and the two inclusive screening cut-offs.
"""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import (
    add_invoice,
    add_transport_document,
    api_client,
    assert_credit_drawing_ledger,
    assert_drawing_identity,
    assert_end_of_day_instant,
    assert_facility_ledger,
    assert_fields_equal,
    assert_issuance_charges,
    assert_net_proceeds_identity,
    assert_screening_outcome,
    assert_settlement_waterfall,
    complying_presentation,
    conclude_examination,
    create_bank,
    credit_officer_headers,
    factories,
    issued_credit,
    list_claim_rows,
    lodge_claim,
    open_presentation,
    raise_discrepancy,
    refuse_presentation,
    request_confirmation,
    rescreen_presentation,
    set_clock,
    settle_claim,
    setup_parties,
    submit_presentation,
    submitted_presentation,
    trade_finance_officer_headers,
)

MONDAY_14 = "2026-09-14T09:00:00Z"
THURSDAY_17 = "2026-09-17T09:00:00Z"

# A Norwegian applicant and advising bank against a Latvian beneficiary: no party sits in a
# sanctioned country, and the advising bank is not domiciled in the beneficiary's own.
_APPLICANT = {"country_code": "NO"}
_BANK = {"country_code": "NO", "country_risk_score": 12, "credit_rating": "AA"}
_BENEFICIARY = {"country_code": "LV"}


def _parties(limit_cents=50000000, bank=None, beneficiary=None, **facility_overrides):
    facility = {"limit_cents": limit_cents, "collateral_required_pct": 0}
    facility.update(facility_overrides)
    return setup_parties(
        applicant=dict(_APPLICANT),
        facility=facility,
        bank=dict(_BANK if bank is None else bank),
        beneficiary=dict(_BENEFICIARY if beneficiary is None else beneficiary),
    )


def _read_bank(bank_id):
    return validate_success(api_client.get_bank(bank_id, credit_officer_headers()))


class TestDrawableLedgerIgnoresUnsubmittedAndVoidedPresentations:
    """One file that never leaves `RECEIVED` and one that is refused after submission."""

    def test_a_file_still_at_received_carries_documents_but_reserves_nothing(self, clock):
        """The 2,000,000 invoice is on file, yet `drawn_amount_cents` is still zero.

        PRD 3.6: "`examination_deadline` deliberately stays unset until submission: the five
        banking days run from the day the documents are actually presented as a complete set,
        not from the day the file was opened."

        PRD 3.6: "A presentation still at `RECEIVED` has not frozen its drawn amount and
        belongs to neither set; a presentation whose `settlement_status` is `VOID` belongs to
        neither set either, which is precisely what makes refusal a clean compensating
        action."

        Design: Corner/calculations/credit_drawable_ledger_excludes_received_and_void_presentations
        """
        parties = _parties()
        ctx = issued_credit(parties)
        set_clock(MONDAY_14)

        pa = open_presentation(ctx)
        add_invoice(pa, 2000000)

        file_row = pa.refresh()
        assert_fields_equal(
            file_row,
            examination_status="RECEIVED",
            settlement_status="UNSETTLED",
            document_count=1,
            drawn_amount_cents=0,
        )
        assert file_row["examination_deadline"] is None
        credit = ctx.refresh()
        assert_credit_drawing_ledger(
            credit, reserved_cents=0, drawn_settled_cents=0, available_cents=10000000
        )
        assert_drawing_identity(credit)
        assert_facility_ledger(parties.refresh_facility(), allocated_cents=10025000)

    def test_refusal_voids_the_drawing_and_walks_the_reservation_back_to_zero(self, clock):
        """`reserved_cents` runs 0 to 3,000,000 and back to 0 while the other file sits still.

        PRD 3.6: "Submission freezes the money figures. `drawn_amount_cents` becomes the sum
        of `invoice_amount_cents` over the file's `COMMERCIAL_INVOICE` documents and is never
        re-summed afterwards, and `document_count` is likewise frozen."

        PRD 3.7: "Hop three follows from hop two: `available_cents` is re-derived as
        `max_drawable_cents` minus `reserved_cents` minus `drawn_settled_cents`, restoring
        precisely the value the credit had before the submission, and the credit's `version`
        increments."

        Design: Corner/calculations/credit_drawable_ledger_excludes_received_and_void_presentations
        """
        parties = _parties()
        ctx = issued_credit(parties)
        set_clock(MONDAY_14)
        pa = open_presentation(ctx)
        add_invoice(pa, 2000000)

        pb = submitted_presentation(ctx, invoice_amounts=(3000000,))
        mid = ctx.refresh()
        raise_discrepancy(pb, "GOODS_DESCRIPTION_MISMATCH")
        conclude_examination(pb)
        refuse_presentation(pb)

        assert pb.presentation["drawn_amount_cents"] == 3000000
        assert_credit_drawing_ledger(mid, reserved_cents=3000000, available_cents=7000000)
        assert_fields_equal(
            pb.refresh(), examination_status="REFUSED", settlement_status="VOID"
        )
        after = ctx.refresh()
        assert_credit_drawing_ledger(
            after, reserved_cents=0, drawn_settled_cents=0, available_cents=10000000
        )
        assert pa.refresh()["examination_status"] == "RECEIVED"
        assert_facility_ledger(parties.refresh_facility(), allocated_cents=10025000)


class TestExaminationDeadlineWalksFiveBankingDays:
    """A Monday presentation and a Thursday presentation on the same credit."""

    def test_a_monday_file_lands_on_the_following_monday_and_skips_the_weekend(self, clock):
        """Tue, Wed, Thu, Fri and Mon are the five counted days, so 2026-09-21 is the deadline.

        PRD 3.6: "Start from `received_date` and walk forward one calendar day at a time,
        counting a day only when it is Monday through Friday, until five have been counted;
        the day the walk lands on is the deadline date."

        PRD 3.6: "There is no holiday calendar: Saturday and Sunday are the only non-banking
        days, so the deadline is reproducible from the date alone."

        Design: Corner/calculations/examination_period_deadline_counts_five_banking_days_and_skips_the_weekend
        """
        parties = _parties()
        ctx = issued_credit(parties)
        set_clock(MONDAY_14)

        pm = submitted_presentation(ctx, invoice_amounts=(1000000,))

        row = pm.presentation
        assert row["received_date"] == "2026-09-14"
        assert_end_of_day_instant(
            row["examination_deadline"], "2026-09-21", "examination_deadline"
        )
        assert row["examination_deadline"] != "2026-09-19T23:59:59.999Z"
        assert row["maturity_date"] is None

    def test_a_thursday_file_crosses_one_weekend_and_lands_on_the_next_thursday(self, clock):
        """Fri, Mon, Tue, Wed and Thu are counted, so 2026-09-24 is the deadline.

        PRD 3.6: "The day of presentation itself is never counted, even when it is a banking
        day."

        PRD 3.6: "`examination_deadline` is then computed as **five banking days following
        the day of presentation**, at `23:59:59.999Z` on the fifth such day."

        Design: Corner/calculations/examination_period_deadline_counts_five_banking_days_and_skips_the_weekend
        """
        parties = _parties()
        ctx = issued_credit(parties)
        set_clock(MONDAY_14)
        submitted_presentation(ctx, invoice_amounts=(1000000,))
        pt = open_presentation(ctx)
        add_invoice(pt, 1000000)
        add_transport_document(pt)

        set_clock(THURSDAY_17)
        submit_presentation(pt)

        row = pt.refresh()
        assert row["received_date"] == "2026-09-17"
        assert_end_of_day_instant(
            row["examination_deadline"], "2026-09-24", "examination_deadline"
        )
        assert row["examination_deadline"] != "2026-09-22T23:59:59.999Z"
        assert row["maturity_date"] is None
        assert_credit_drawing_ledger(
            ctx.refresh(), reserved_cents=2000000, available_cents=8000000
        )


class TestSettlementProceedsRoundHalfUpAtTheExactHalfCent:
    """A drawn amount of 2,501,250 puts both money components on a rounding tie."""

    @staticmethod
    def _lodged(parties):
        ctx = issued_credit(parties, amount_cents=3000000)
        set_clock(MONDAY_14)
        pctx = complying_presentation(ctx, invoice_amounts=(2501250,))
        return ctx, pctx, lodge_claim(pctx, "PAYMENT", 2501250)

    def test_both_ties_round_away_from_zero_rather_than_truncating(self, clock):
        """Commission 3,001.5 becomes 3,002 and the invoice fee 1,250.625 becomes 1,251.

        PRD 2.6: "Because every stored amount is already an exact whole number of cents, the
        specification's two-decimal-place presentation and its half-up rounding rule coincide:
        wherever a computation produces a fraction of a cent, that fraction is resolved by
        rounding half up — to the nearest whole cent, with an exact half rounded away from
        zero."

        PRD 3.9: "A `COMMERCIAL_INVOICE` contributes its `invoice_amount_cents` multiplied by
        5 basis points, divided by 10,000 and rounded half up; every other document type
        contributes a flat 3,500 cents."

        Design: Corner/calculations/settlement_proceeds_rounds_half_up_at_the_exact_half_cent
        """
        parties = _parties()
        _ctx, _pctx, claim = self._lodged(parties)

        settled = settle_claim(claim["id"])

        assert_settlement_waterfall(
            settled,
            variant_applied="SIGHT_HONOUR",
            commission_bps_applied=12,
            commission_cents=3002,
            discount_cents=0,
            doc_examination_fee_cents=4751,
            days_to_maturity=0,
            net_proceeds_cents=2493497,
            status="SETTLED",
        )
        assert settled["commission_cents"] != 3001
        assert settled["doc_examination_fee_cents"] != 4750
        assert settled["net_proceeds_cents"] != 2493499
        assert_net_proceeds_identity(settled, 2501250)

    def test_the_sight_honour_moves_the_drawing_from_reserved_into_settled(self, clock):
        """The file is `PAID` and `available_cents` is the 498,750 left under the ceiling.

        PRD 3.9: "A sight honour on a `PAYMENT` claim moves `CLAIM_LODGED → PAID`, and the
        drawing moves out of the credit's `reserved_cents` into its `drawn_settled_cents` —
        both by exactly `drawn_amount_cents`, so `available_cents` is unchanged by
        settlement."

        PRD 3.9: "Step four deducts the charges from the drawn amount in the fixed order
        commission, then discount, then document fees: `net_proceeds_cents` is
        `drawn_amount_cents` minus `commission_cents` minus `discount_cents` minus
        `doc_examination_fee_cents`."

        Design: Corner/calculations/settlement_proceeds_rounds_half_up_at_the_exact_half_cent
        """
        parties = _parties()
        ctx, pctx, claim = self._lodged(parties)

        settle_claim(claim["id"])

        assert_fields_equal(
            pctx.refresh(), settlement_status="PAID", examination_status="COMPLYING"
        )
        credit = ctx.refresh()
        assert_credit_drawing_ledger(
            credit,
            drawn_settled_cents=2501250,
            reserved_cents=0,
            available_cents=498750,
            max_drawable_cents=3000000,
        )
        assert credit["status"] == "ISSUED"
        assert_drawing_identity(credit)
        rows = list_claim_rows(pctx.presentation_id)
        assert len(rows) == 1
        assert rows[0]["status"] == "SETTLED"


class TestAcceptanceVariantIsChosenByClaimTypeAndReservesRatherThanDraws:
    """An ACCEPTANCE credit with a 90-day tenor, claimed and settled a week after presentation."""

    ACCEPTANCE_TERMS = {"available_by": "ACCEPTANCE", "tenor_days": 90}

    def test_the_tenor_prices_three_months_of_usance_and_sets_a_maturity_date(self, clock):
        """Ninety days is three whole months, so gross exposure is 10,075,000 not 10,000,000.

        PRD 3.3: "Step two prices the usance risk add-on in whole months rounded **up**: for
        a credit available by `SIGHT_PAYMENT` the month count is zero, and otherwise it is
        `tenor_days` divided by 30 and rounded up to the next whole number; the add-on is
        then `max_drawable_cents` multiplied by 25, multiplied by that month count, divided
        by 10,000 with the remainder discarded — twenty-five basis points of the drawable
        ceiling for every whole or part month of usance."

        PRD 3.6: "`submitted_at` is set to the clock instant, `received_date` is set to the
        clock date at submission, and `maturity_date` becomes the clock date plus the credit's
        `tenor_days` when `available_by` is anything other than `SIGHT_PAYMENT`, and stays
        unset for a sight credit whose `tenor_days` is zero."

        Design: Corner/calculations/settlement_variant_selection_acceptance_then_reimbursement_reuse
        """
        parties = _parties()
        ctx = issued_credit(parties, **self.ACCEPTANCE_TERMS)

        set_clock(MONDAY_14)
        pctx = submitted_presentation(ctx, invoice_amounts=(4000000,))

        assert_issuance_charges(
            ctx.credit,
            gross_exposure_cents=10075000,
            committed_allocation_cents=10075000,
            base_commission_cents=25000,
            chargeable_utilisation_cents=10100000,
        )
        assert ctx.credit["gross_exposure_cents"] != 10000000
        assert pctx.presentation["maturity_date"] == "2026-12-13"
        assert_facility_ledger(parties.refresh_facility(), allocated_cents=10100000)

    def test_the_acceptance_claim_discounts_to_maturity_and_leaves_the_money_committed(
        self, clock
    ):
        """Eighty-three days of discount, and the file lands on `ACCEPTED` rather than `PAID`.

        PRD 3.9: "Step three is the discount charge, which applies only to the usance forms:
        for a sight honour, `days_to_maturity` is 0 and `discount_cents` is 0, while for the
        usance forms `days_to_maturity` is the whole number of days from the clock date to the
        presentation's `maturity_date` and `discount_cents` is `drawn_amount_cents` multiplied
        by 450 basis points, multiplied by `days_to_maturity`, divided by the product of
        10,000 and a 360-day year basis, rounded half up."

        PRD 3.9: "An acceptance or deferred payment moves `CLAIM_LODGED → ACCEPTED` and
        deliberately does **not** release `reserved_cents` and does not raise
        `drawn_settled_cents`: the bank's undertaking runs until maturity, so the money stays
        committed."

        Design: Corner/calculations/settlement_variant_selection_acceptance_then_reimbursement_reuse
        """
        parties = _parties()
        ctx = issued_credit(parties, **self.ACCEPTANCE_TERMS)
        set_clock(MONDAY_14)
        pctx = complying_presentation(ctx, invoice_amounts=(4000000,))
        claim = lodge_claim(pctx, "ACCEPTANCE", 4000000)
        set_clock("2026-09-21T09:00:00Z")

        settled = settle_claim(claim["id"])

        assert_settlement_waterfall(
            settled,
            variant_applied="ACCEPTANCE_AT_MATURITY",
            commission_bps_applied=20,
            commission_cents=8000,
            days_to_maturity=83,
            discount_cents=41500,
            doc_examination_fee_cents=5500,
            net_proceeds_cents=3945000,
            status="SETTLED",
        )
        assert_net_proceeds_identity(settled, 4000000)
        file_row = pctx.refresh()
        assert file_row["settlement_status"] == "ACCEPTED"
        assert file_row["settlement_status"] != "PAID"
        credit = ctx.refresh()
        assert_credit_drawing_ledger(
            credit, reserved_cents=4000000, drawn_settled_cents=0, available_cents=6000000
        )
        assert credit["status"] == "ISSUED"


class TestNegotiationWaterfallRunsCommissionThenDiscountThenDocumentFees:
    """Two claims on one NEGOTIATION credit share every rate and differ only in size."""

    NEGOTIATION_TERMS = {"available_by": "NEGOTIATION", "tenor_days": 60}

    def test_the_large_claim_runs_the_whole_waterfall_down_to_its_net(self, clock):
        """12,000 of commission, 44,250 of discount over 59 days and 6,500 of document fees.

        PRD 3.9: "`NEGOTIATION_UNDER_DISCOUNT` applies to a `NEGOTIATION` claim: commission at
        20 basis points and a discount charged for the whole run from the settlement date to
        `maturity_date` on the 360-day basis, so the same drawn amount and the same documents
        yield materially smaller proceeds."

        PRD 3.9: "Step two is the per-document examination fee, and its rounding order is
        pinned: walk the presentation's PresentedDocument rows in `created_at` ascending order,
        and for each one round its own fee to whole cents **before** adding it to the running
        total."

        Design: Corner/calculations/settlement_waterfall_deducts_commission_then_discount_then_document_fees
        """
        parties = _parties()
        ctx = issued_credit(parties, **self.NEGOTIATION_TERMS)
        set_clock(MONDAY_14)
        p1 = complying_presentation(ctx, invoice_amounts=(6000000,))
        claim = lodge_claim(p1, "NEGOTIATION", 6000000)
        set_clock("2026-09-15T09:00:00Z")

        settled = settle_claim(claim["id"])

        assert_issuance_charges(
            ctx.credit,
            gross_exposure_cents=10050000,
            base_commission_cents=25000,
            chargeable_utilisation_cents=10075000,
        )
        assert p1.presentation["maturity_date"] == "2026-11-13"
        assert_settlement_waterfall(
            settled,
            variant_applied="NEGOTIATION_UNDER_DISCOUNT",
            commission_bps_applied=20,
            commission_cents=12000,
            days_to_maturity=59,
            discount_cents=44250,
            doc_examination_fee_cents=6500,
            net_proceeds_cents=5937250,
            status="SETTLED",
        )
        assert_net_proceeds_identity(settled, 6000000)
        assert p1.refresh()["settlement_status"] == "NEGOTIATED"

    def test_a_claim_whose_flat_document_fee_swamps_it_is_refused_outright(self, clock):
        """3,000 of proceeds cannot carry a 3,502 fee, so the settlement bottoms out below zero.

        PRD 3.9: "The net may never go below zero, and a result that would be negative is
        refused with `ERR_CHARGES_EXCEED_PROCEEDS` (422)."

        PRD 3.9: "Every row contributes, not only invoices. Summing exact per-document amounts
        and rounding once at the end is wrong and can differ from the correct answer by up to
        half the `document_count`."

        Design: Corner/calculations/settlement_waterfall_deducts_commission_then_discount_then_document_fees
        """
        parties = _parties()
        ctx = issued_credit(parties, **self.NEGOTIATION_TERMS)
        set_clock(MONDAY_14)
        p1 = complying_presentation(ctx, invoice_amounts=(6000000,))
        c1 = lodge_claim(p1, "NEGOTIATION", 6000000)
        p2 = complying_presentation(ctx, invoice_amounts=(3000,))
        c2 = lodge_claim(p2, "NEGOTIATION", 3000)
        set_clock("2026-09-15T09:00:00Z")
        settle_claim(c1["id"])

        response = api_client.settle_claim(
            c2["id"], factories.settle_payload(), trade_finance_officer_headers()
        )

        validate_error(response, "ERR_CHARGES_EXCEED_PROCEEDS", 422)
        rows = list_claim_rows(p2.presentation_id)
        assert len(rows) == 1
        assert rows[0]["status"] == "LODGED"
        assert p2.refresh()["settlement_status"] == "CLAIM_LODGED"
        credit = ctx.refresh()
        assert_credit_drawing_ledger(
            credit,
            drawn_settled_cents=6000000,
            reserved_cents=3000,
            available_cents=3997000,
        )
        assert credit["status"] == "ISSUED"


class TestPresentationAndConfirmationWindowsUseOppositeBounds:
    """Three issued credits whose two windows are cut from the same two dates."""

    LATER_EXPIRY = {"latest_shipment_date": "2026-11-25", "expiry_date": "2026-12-10"}

    def test_the_presentation_deadline_takes_the_earlier_of_the_two_candidate_dates(
        self, clock
    ):
        """The shipment cutoff wins on one credit and the expiry date wins on the other.

        PRD 3.2: "The `presentation_deadline_date` is the earlier of the `expiry_date` and the
        date obtained by adding `presentation_period_days` calendar days to
        `latest_shipment_date`; that resulting date is an inclusive upper bound."

        PRD 3.3: "The confirmation window is opened with `confirmation_window_start` equal to
        `issue_date`, inclusive, and `confirmation_window_end` equal to `expiry_date` advanced
        by `presentation_period_days` days — and that end date is **exclusive**, which is a
        different convention from the presentation deadline on purpose."

        Design: Corner/calculations/presentation_window_takes_the_min_and_mixes_closed_and_open_bounds
        """
        parties = _parties()

        w1 = issued_credit(parties)
        w2 = issued_credit(parties, **self.LATER_EXPIRY)

        assert_fields_equal(
            w1.credit,
            presentation_deadline_date="2026-11-21",
            confirmation_window_start="2026-08-10",
            confirmation_window_end="2026-12-21",
        )
        assert_fields_equal(
            w2.credit,
            presentation_deadline_date="2026-12-10",
            confirmation_window_start="2026-08-10",
            confirmation_window_end="2026-12-31",
        )

    def test_the_confirmation_window_admits_its_start_date_and_bars_its_end_date(self, clock):
        """2026-12-20 is inside one window, 2026-12-21 is outside it and inside the other.

        PRD 2.11: "The **confirmation window** runs from `confirmation_window_start`
        **inclusive** to `confirmation_window_end` **exclusive**. A request on the start date
        is inside the window; a request on the end date is outside it."

        PRD 3.4: "The clock date must fall inside the credit's half-open confirmation window,
        on or after `confirmation_window_start` and strictly before `confirmation_window_end`,
        else `ERR_CONFIRMATION_WINDOW_CLOSED` (422)."

        Design: Corner/calculations/presentation_window_takes_the_min_and_mixes_closed_and_open_bounds
        """
        parties = _parties()
        bch = create_bank(
            bank_name="Banque Cantonale Helvetique",
            country_code="CH",
            country_risk_score=15,
            credit_rating="AA",
            confirmation_appetite_cents=40000000,
        )
        w1 = issued_credit(parties)
        w2 = issued_credit(parties, **self.LATER_EXPIRY)
        w3 = issued_credit(parties)

        set_clock("2026-12-20T09:00:00Z")
        request_confirmation(w3.credit_id, bch["id"])
        set_clock("2026-12-21T09:00:00Z")
        too_late = api_client.create_confirmation_request(
            w1.credit_id,
            factories.confirmation_request_payload(bch["id"]),
            trade_finance_officer_headers(),
        )
        request_confirmation(w2.credit_id, bch["id"])

        assert w3.refresh()["confirmation_status"] == "CONFIRMATION_REQUESTED"
        validate_error(too_late, "ERR_CONFIRMATION_WINDOW_CLOSED", 422)
        barred = w1.refresh()
        assert barred["confirmation_status"] == "UNCONFIRMED"
        assert barred["confirming_bank_id"] is None
        assert w2.refresh()["confirmation_status"] == "CONFIRMATION_REQUESTED"
        assert _read_bank(bch["id"])["confirming_line_used_cents"] == 20000000
        assert_facility_ledger(parties.refresh_facility(), allocated_cents=30075000)


class TestConfirmingBankSelectorFiltersBeforeItScores:
    """Eight banks on file, two of them the highest scorers and both ineligible."""

    ADVISING = {
        "bank_name": "Alfa Latvia Bank",
        "country_code": "LV",
        "country_risk_score": 25,
        "credit_rating": "A",
        "confirmation_appetite_cents": 90000000,
    }
    LATER = (
        ("B7", "Amstel Trade Bank", "NL", 20, "AA", 90000000, False),
        ("B2", "Helvetia Trade Bank", "CH", 15, "A", 90000000, False),
        ("B3", "Straits Commerce Bank", "SG", 40, "AA", 90000000, False),
        ("B5", "Bosphorus Ticaret Bank", "TR", 70, "AA", 90000000, False),
        ("B6", "Gulf Crescent Bank", "AE", 10, "AA", 90000000, True),
        ("B8", "Kanto Shoko Bank", "JP", 5, "AA", 5000000, False),
    )

    @classmethod
    def _register(cls):
        parties = _parties(
            bank=dict(cls.ADVISING),
            beneficiary={"beneficiary_name": "Riga Sawmill SIA", "country_code": "LV"},
        )
        banks = {"ALV": parties.advising_bank}
        banks["B1"] = create_bank(
            bank_name="Rheinhandel Bank",
            country_code="DE",
            country_risk_score=20,
            credit_rating="AA",
            confirmation_appetite_cents=90000000,
        )
        set_clock("2026-08-10T09:05:00Z")
        for label, name, country, risk, rating, appetite, flagged in cls.LATER:
            banks[label] = create_bank(
                bank_name=name,
                country_code=country,
                country_risk_score=risk,
                credit_rating=rating,
                confirmation_appetite_cents=appetite,
                sanctions_flag=flagged,
            )
        return parties, banks

    def test_the_two_top_scorers_are_filtered_out_and_the_earlier_of_a_tie_wins(self, clock):
        """B8 and B6 outscore everyone and neither is a candidate; B1 beats B7 on `created_at`.

        PRD 3.4: "The candidate pool is every registered bank whose `status` is `ACTIVE`, whose
        `sanctions_flag` is false, whose `country_risk_score` is at most 60, whose
        `country_code` differs from the beneficiary's `country_code`, which has not already
        returned a decline on this very credit, and whose peak concurrent occupancy including
        this candidate credit is at most its own `confirmation_appetite_cents`."

        PRD 3.4: "Ties are broken first by the lower `country_risk_score` and then by the
        earlier `created_at` — never by identifier."

        Design: Corner/calculations/confirming_bank_selection_ranks_by_weighted_score_then_created_at
        """
        parties, banks = self._register()
        ctx = issued_credit(parties)

        request_confirmation(ctx.credit_id)

        credit = ctx.refresh()
        assert credit["confirming_bank_id"] == banks["B1"]["id"]
        assert credit["confirming_bank_id"] != banks["B8"]["id"]
        assert credit["confirming_bank_id"] != banks["B6"]["id"]
        assert credit["confirming_bank_id"] != banks["B7"]["id"]
        assert credit["confirmation_status"] == "CONFIRMATION_REQUESTED"

    def test_every_bank_carries_its_derived_score_and_only_the_winner_carries_the_line(
        self, clock
    ):
        """The scores are derived at registration for candidates and non-candidates alike.

        PRD 3.1: "Its `eligibility_score` is derived immediately: take 100 minus
        `country_risk_score`, multiply by 6, and add the rating points multiplied by 4, where
        the rating points are 100 for `AA`, 75 for `A`, 50 for `BBB` and 25 for `BB`."

        PRD 3.4: "A successful request sets the credit's `confirming_bank_id` to the named or
        selected bank, moves `confirmation_status` to `CONFIRMATION_REQUESTED`, re-derives that
        bank's `confirming_line_used_cents` and increments the bank's `version` by one, and
        increments the credit's own `version` by one."

        Design: Corner/calculations/confirming_bank_selection_ranks_by_weighted_score_then_created_at
        """
        parties, banks = self._register()
        ctx = issued_credit(parties)

        request_confirmation(ctx.credit_id)

        expected_scores = {
            "B1": 880,
            "B7": 880,
            "B2": 810,
            "B3": 760,
            "B5": 580,
            "B6": 940,
            "B8": 970,
            "ALV": 750,
        }
        for label, score in expected_scores.items():
            row = _read_bank(banks[label]["id"])
            assert row["eligibility_score"] == score, f"{label} scored {row['eligibility_score']}"
        assert _read_bank(banks["B1"]["id"])["confirming_line_used_cents"] == 10000000
        assert _read_bank(banks["B7"]["id"])["confirming_line_used_cents"] == 0
        assert _read_bank(banks["B8"]["id"])["confirming_line_used_cents"] == 0


class TestSanctionsScoreSitsExactlyOnBothInclusiveThresholds:
    """Three files bracket the review cut-off and the block cut-off to the point."""

    TIMBER = {
        "goods_description": "Kiln dried pine boards",
        "hs_code": "440710",
        "consignee_country": "NO",
    }

    @staticmethod
    def _file_with(ctx, **invoice_overrides):
        pctx = open_presentation(ctx)
        add_invoice(pctx, 1000000, **invoice_overrides)
        return pctx

    def test_two_high_risk_transit_codes_on_one_document_are_two_hits_and_reach_forty(
        self, clock
    ):
        """Two pairs score 40 and review; one pair scores 20 and clears.

        PRD 3.8: "`transit_hits` is counted differently from the others: it is the number of
        document-and-transit-code **pairs** where the transit code is a high-risk transit code
        and is not also a sanctioned code, so one document routed through two high-risk
        countries contributes two transit hits, while a transit through a sanctioned country
        contributes to `country_hits` and never to `transit_hits`."

        PRD 3.8: "The `result` follows from the score against two inclusive lower bounds: a
        score of 100 or more gives `BLOCKED`, a score of 40 or more but below 100 gives
        `HIT_PENDING_REVIEW`, and anything below 40 gives `CLEAR`."

        Design: Corner/calculations/sanctions_dual_use_score_sits_exactly_on_both_thresholds
        """
        parties = _parties()
        ctx = issued_credit(parties)
        set_clock(MONDAY_14)
        px = self._file_with(ctx, transit_country_codes=["AE", "HK"], **self.TIMBER)
        py = self._file_with(ctx, transit_country_codes=["AE"], **self.TIMBER)

        x_check = rescreen_presentation(px)
        y_check = rescreen_presentation(py)

        assert_screening_outcome(
            x_check,
            scope="PRESENTED_DOCUMENTS",
            transit_hits=2,
            country_hits=0,
            risk_score=40,
            result="HIT_PENDING_REVIEW",
        )
        assert_screening_outcome(
            y_check,
            scope="PRESENTED_DOCUMENTS",
            transit_hits=1,
            country_hits=0,
            risk_score=20,
            result="CLEAR",
        )

    def test_a_dual_use_prefix_plus_a_controlled_keyword_reaches_exactly_one_hundred(
        self, clock
    ):
        """60 plus 40 is the block boundary, and the block reaches the beneficiary.

        PRD 3.8: "`risk_score` is 100 per country hit, plus 60 per dual-use hit, plus 40 per
        keyword hit, plus 20 per transit hit, and the total is then capped at 200 — a score
        never exceeds 200 however many hits accumulate."

        PRD 3.8: "When a document-scope check scores `BLOCKED`, the beneficiary of the credit
        is moved `ACTIVE → BLOCKED`, which itself bars that beneficiary from being named on any
        new credit."

        Design: Corner/calculations/sanctions_dual_use_score_sits_exactly_on_both_thresholds
        """
        parties = _parties()
        ctx = issued_credit(parties)
        set_clock(MONDAY_14)
        pz = self._file_with(
            ctx,
            goods_description="Titanium maraging steel forgings",
            hs_code="8542310000",
            consignee_country="NO",
            transit_country_codes=[],
        )

        z_check = rescreen_presentation(pz)

        assert_screening_outcome(
            z_check,
            scope="PRESENTED_DOCUMENTS",
            dual_use_hits=1,
            keyword_hits=1,
            transit_hits=0,
            country_hits=0,
            risk_score=100,
            result="BLOCKED",
        )
        beneficiary = validate_success(
            api_client.get_beneficiary(
                parties.beneficiary_id, trade_finance_officer_headers()
            )
        )
        assert beneficiary["status"] == "BLOCKED"

    def test_a_party_scope_rerun_scores_the_three_counterparties_and_names_no_file(
        self, clock
    ):
        """The party sweep finds nothing on a Norwegian applicant, a Latvian seller and a Nordic bank.

        PRD 3.8: "For the `CREDIT_PARTIES` scope the inputs are exactly three parties — the
        credit's applicant, its beneficiary and its advising bank."

        PRD 3.8: "Every check carries the `credit_id` it belongs to — always set, including for
        document-scope checks, where it is taken from the presentation's credit — a
        `presentation_id` set only when the `scope` is `PRESENTED_DOCUMENTS` and unset for
        `CREDIT_PARTIES`, the `scope` itself, the four hit counters `country_hits`,
        `dual_use_hits`, `keyword_hits` and `transit_hits`, the resulting `risk_score`, and a
        `result` that is one of `PENDING`, `CLEAR`, `HIT_PENDING_REVIEW`, `BLOCKED`, `RELEASED`
        or `ESCALATED`, starting at `PENDING`."

        Design: Corner/calculations/sanctions_dual_use_score_sits_exactly_on_both_thresholds
        """
        parties = _parties()
        ctx = issued_credit(parties)
        set_clock(MONDAY_14)
        py = self._file_with(ctx, transit_country_codes=["AE"], **self.TIMBER)

        party_check = rescreen_presentation(py, scope="CREDIT_PARTIES")

        assert_screening_outcome(
            party_check,
            scope="CREDIT_PARTIES",
            country_hits=0,
            dual_use_hits=0,
            keyword_hits=0,
            transit_hits=0,
            risk_score=0,
            result="CLEAR",
        )
        assert party_check["presentation_id"] is None
        assert party_check["credit_id"] == ctx.credit_id
        assert_credit_drawing_ledger(
            ctx.refresh(), reserved_cents=0, available_cents=10000000
        )
